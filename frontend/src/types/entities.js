// API实体字段约定：来源{id,natural_key,data}、口径{id,version,data}、报告{id,status,snapshot,checksum,result,approved}、计划{next_at,enabled}、归因{id,pair_key,base_run,compare_run,period,result,created}。
export const ENTITY_KEYS=['sources','policies','runs','schedules','deliveries','attributions'];
