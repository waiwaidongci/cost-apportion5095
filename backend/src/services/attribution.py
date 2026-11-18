import time
from fractions import Fraction
from itertools import combinations,permutations
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from src.models.run import Run,Attribution
from src.services.calculation import calculate
from src.services.audit import log
FACTORS=('amount','classification','weight')
LABELS={'amount':'金额','classification':'归类','weight':'权重'}
ORDERS=list(permutations(FACTORS))
def _vouchers(run):
 snap=run.snapshot or {}
 keys=snap.get('vouchers');sources=snap.get('sources') or []
 if not isinstance(keys,list) or len(keys)!=len(sources) or not all(isinstance(k,str) and k for k in keys):
  raise HTTPException(422,f'报告#{run.id}未冻结凭证身份，无法参与归因；旧报告仍可查看原账')
 if len(set(keys))!=len(keys): raise HTTPException(422,f'报告#{run.id}凭证身份重复，无法归因')
 return dict(zip(keys,sources))
def _pivot(rows): return {(r['期间'],r['部门'],r['费用类别']):r['分摊金额分'] for r in rows}
def _stored(run): return _pivot((run.result or {}).get('rows') or [])
def _out(value): return round(float(value),4)
def compute(base,compare):
 """仅用两份报告的冻结快照与留存结果重算差额归因；不读取当前底稿或口径，并发修改不影响归因。"""
 for run in (base,compare):
  if run.status!='completed' or not run.result: raise HTTPException(409,f'报告#{run.id}尚未完成，不能归因')
 period=(base.snapshot or {}).get('period')
 if period!=(compare.snapshot or {}).get('period'): raise HTTPException(422,'两份报告期间不一致，请选择同期间报告')
 a_map=_vouchers(base);b_map=_vouchers(compare)
 keys=sorted(set(a_map)|set(b_map))
 added=[k for k in keys if k not in a_map];removed=[k for k in keys if k not in b_map]
 changed=[k for k in keys if k in a_map and k in b_map and a_map[k]!=b_map[k]]
 amounts={};classes={}
 for k in keys:
  ra,rb=a_map.get(k),b_map.get(k)
  cls_a=(ra['period'],ra['department'],ra['category']) if ra else (rb['period'],rb['department'],rb['category'])
  cls_b=(rb['period'],rb['department'],rb['category']) if rb else cls_a
  amounts[k]=(ra['amount_cents'] if ra else 0,rb['amount_cents'] if rb else 0)
  classes[k]=(cls_a,cls_b)
 policy_a=(base.snapshot or {}).get('policy') or {};policy_b=(compare.snapshot or {}).get('policy') or {}
 if not isinstance(policy_a.get('weights'),dict) or not isinstance(policy_b.get('weights'),dict):
  raise HTTPException(422,'报告快照缺少口径权重，无法归因')
 def pivot_for(subset):
  sources=[]
  for k in keys:
   amount=amounts[k][1] if 'amount' in subset else amounts[k][0]
   cls=classes[k][1] if 'classification' in subset else classes[k][0]
   sources.append({'period':cls[0],'department':cls[1],'category':cls[2],'amount_cents':amount})
  side=policy_b if 'weight' in subset else policy_a
  return _pivot(calculate(sources,{'version':side.get('version') or '归因重算','weights':side['weights']})['rows'])
 states={frozenset(combo):pivot_for(combo) for r in range(4) for combo in combinations(FACTORS,r)}
 nz=lambda p:{k:v for k,v in p.items() if v}
 states={k:nz(p) for k,p in states.items()}
 stored_a=nz(_stored(base));stored_b=nz(_stored(compare))
 empty,full=frozenset(),frozenset(FACTORS)
 if states[empty]!=stored_a or states[full]!=stored_b:
  raise HTTPException(422,'对账不符：冻结快照重算结果与报告留存结果不一致，拒绝归因')
 cells=sorted(set().union(*(set(p) for p in states.values()),stored_a,stored_b))
 contrib={f:{c:Fraction(0) for c in cells} for f in FACTORS}
 for order in ORDERS:
  subset=empty;prev=states[empty]
  for f in order:
   subset=subset|{f};cur=states[subset]
   for c in cells: contrib[f][c]+=Fraction(cur.get(c,0)-prev.get(c,0),6)
   prev=cur
 rows=[];totals={f:Fraction(0) for f in FACTORS}
 for c in cells:
  a,b=stored_a.get(c,0),stored_b.get(c,0)
  parts={f:contrib[f][c] for f in FACTORS}
  if sum(parts.values(),Fraction(0))!=b-a:
   raise HTTPException(422,'对账不符：因子贡献合计与两份报告差额不一致，拒绝归因')
  for f in FACTORS: totals[f]+=parts[f]
  if a or b or any(parts.values()):
   rows.append({'期间':c[0],'部门':c[1],'费用类别':c[2],'基准分':a,'对比分':b,'差额分':b-a,'金额贡献分':_out(parts['amount']),'归类贡献分':_out(parts['classification']),'权重贡献分':_out(parts['weight'])})
 total_a,total_b=sum(stored_a.values()),sum(stored_b.values())
 return {'base_run':base.id,'compare_run':compare.id,'period':period,
 'summary':{'基准总额分':total_a,'对比总额分':total_b,'差额分':total_b-total_a,'金额贡献分':_out(totals['amount']),'归类贡献分':_out(totals['classification']),'权重贡献分':_out(totals['weight'])},
 'cells':rows,'vouchers':{'新增':added,'删除':removed,'变更':changed},
 'orders':['→'.join(LABELS[f] for f in o) for o in ORDERS],
 'method':'仅使用两份报告的冻结快照与留存结果重算，归因期间不读取当前底稿或口径。金额、归类（部门和类别）、权重三因子按全部6种替换顺序依次替换重算，因子贡献取6种顺序的平均并保留4位小数；每个部门×类别的三因子贡献之和等于该格两份报告的差额。凭证新增或删除时，缺失版本按零元与另一版的归类参与计算。',
 'reconciled':True}
def attribute(db,user,base_id,compare_id):
 if base_id==compare_id: raise HTTPException(422,'请选择两份不同的报告')
 key=f'{base_id}:{compare_id}'
 existing=db.query(Attribution).filter_by(pair_key=key).first()
 if existing: return existing
 base=db.get(Run,base_id);compare=db.get(Run,compare_id)
 if not base or not compare: raise HTTPException(404,'报告不存在')
 result=compute(base,compare)
 obj=Attribution(pair_key=key,base_run=base_id,compare_run=compare_id,period=result['period'],result=result,created=time.time())
 db.add(obj);log(db,user.email,'attribution.create',key)
 try: db.commit()
 except IntegrityError:
  db.rollback()
  return db.query(Attribution).filter_by(pair_key=key).first()
 return obj
