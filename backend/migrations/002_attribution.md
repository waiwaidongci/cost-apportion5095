# 002 差额归因

SQLAlchemy启动自动创建 `report_attributions` 表（id、pair_key 唯一、base_run、compare_run、period、result JSON、created）。pair_key 为 `基准报告id:对比报告id`，唯一约束保证重试与并发不新增归因结果；并发冲突时回滚并返回已存在行。

Run 快照自本版本起新增 `vouchers` 字段（与 sources 等长、同序的凭证身份 natural_key 数组），仅影响新提交报告；旧报告快照不变，仍可查看原账与导出，但因缺凭证身份不能参与差额归因。已有数据库升级前需备份。
