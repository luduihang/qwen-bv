# 测试场景覆盖表核对（T-022）

> 对照 TASKS.md 契约总览 21 场景逐一核对（2026-10-06，Phase 7）。
> 结论：**21/21 全覆盖，无缺口，无需改实现**。`pytest tests/ -q` 195 全绿（全 mock，不碰真实网络）。

| # | 场景 | 用例（文件::测试） |
|---|---|---|
| 1 | 数字 mid 输入解析 | test_up_parser.py::test_numeric_inputs（int/数字串/前导零/空格） |
| 2 | space URL 输入解析 | test_up_parser.py::test_space_url（https/http、带 query、mid 路径段） |
| 3 | 非法 UP 输入 | test_up_parser.py::test_invalid_inputs（空/非数字/昵称/其他域名/mid≤0/bool） |
| 4 | 一页视频 | test_bili.py::test_fetch_page_normal_normalization（含 VideoRecord 全字段规范化） |
| 5 | 多页视频 | test_bili.py::test_fetch_all_multi_page_full（60 条/2 页，created 降序） |
| 6 | 最后一页不足 page_size | test_bili.py::test_fetch_all_last_page_short（count=35 → 30+5 终止） |
| 7 | page.count = 0 | test_bili.py::test_fetch_all_count_zero（成功空清单，不落空成功） |
| 8 | 不同页面出现重复 BV | test_bili.py::test_fetch_all_cross_page_dedup（去重保先出现） |
| 9 | 中途某页 timeout | test_bili.py::test_fetch_all_timeout_midpage_retry_success（p2 首次 ReadTimeout） |
| 10 | retry 后成功 | 同 #9 + test_bili.py::test_fetch_page_retry_log_line（退避 1s/2s/4s + retry 日志） |
| 11 | retry 最终失败 | test_bili.py::test_fetch_all_retry_exhausted_timeout（→ timeout）/ ::test_fetch_all_retry_exhausted_5xx（→ fetch_failed，1+3 次调用断言） |
| 12 | Bilibili code != 0 | test_bili.py::test_fetch_page_not_found_codes（-404/-403）/ ::test_fetch_page_other_nonzero_code_fetch_failed（-500） |
| 13 | 风控响应 | test_bili.py::test_fetch_page_risk_control_codes（-352/-412/-509）/ ::test_fetch_page_http_risk_status_no_retry（HTTP 412→risk_control、429→rate_limited，1 次调用）/ ::test_fetch_page_risk_business_code_no_retry + test_api.py::test_error_code_http_matrix[risk_control] / ::test_risk_control_not_200_empty_array（429 非 200 空数组） |
| 14 | 非 JSON 响应 | test_bili.py::test_fetch_page_non_json_invalid_response_no_retry（invalid_response，不重试） |
| 15 | 响应缺 data/list/vlist | test_bili.py::test_fetch_page_missing_fields_invalid_response（缺 data / 缺 page / 缺列表 / 列表非 list，4 组参数） |
| 16 | 原子文件写入 | test_storage.py::test_save_creates_up_dir_and_three_files / ::test_bvids_file_one_per_line_newline_terminated / ::test_videos_jsonl_same_order_and_roundtrip / ::test_manifest_fields_written / ::test_empty_snapshot / ::test_bvids_videos_length_mismatch_rejected |
| 17 | 中途失败不破坏旧 snapshot | test_pipeline.py::test_run_collect_sync_failure_keeps_old_snapshot / ::test_run_collect_storage_failure_keeps_old_snapshot + test_storage.py::test_tmp_write_failure_keeps_old_snapshot（tmp 写失败清理 *.tmp、正式文件不变） |
| 18 | /collect API 成功 | test_api.py::test_collect_success_200_fields_and_files（payload 全字段 + 三文件落盘）/ ::test_collect_success_up_url_input / ::test_collect_success_up_numeric_string / ::test_collect_success_no_tmp_leftover |
| 19 | /collect API 参数错误 | test_api.py::test_collect_invalid_up_400（都缺/都给/mid 非法/up 非法，4 组）/ ::test_collect_non_json_body_400 / ::test_error_json_shape_exact（{"error":{"code","message"}} 精确形状） |
| 20 | GET cached bvids | test_api.py::test_get_bvids_200（mid/count/bvids）/ ::test_get_bvids_never_synced_404 / ::test_get_bvids_non_numeric_mid_400 |
| 21 | GET videos 分页 | test_api.py::test_get_videos_default_slice（offset=0/limit=100）/ ::test_get_videos_offset_limit_slice / ::test_get_videos_clamp_and_defaults（越界 clamp + 非整数默认，4 组）/ ::test_get_videos_beyond_total_empty / ::test_get_videos_never_synced_404 |

## 补充覆盖（超出 21 场景表的 T-019~T-021 增量）

- 错码全矩阵：test_api.py::test_error_code_http_matrix（10 code → 400/404/429/502/504/500 + JSON 形状 + 失败不落盘）
- 同步日志：test_api.py::test_collect_log_lines_success_no_cookie / ::test_collect_log_line_error / ::test_collect_log_line_invalid_up_request + test_bili.py::test_fetch_all_page_log_lines / ::test_fetch_page_retry_log_line（含"日志无 Cookie"断言）
- wbi 签名：test_wbi.py（24 例，T-007）；sync_up 完整性校验：test_sync.py（9 例，T-014，含 500→430 与 1% 边界）；config 加载：test_config.py（8 场景）；health/启动：test_app.py
