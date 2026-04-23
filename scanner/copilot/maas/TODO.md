# MAAS TODO

## Prompt Tuning
- [ ] Update logs specialist prompt to list actual available tool names (e.g., `get_dag_run_history`, `mcp_airflow__list_dags`, `mcp_airflow__diagnose_dag_run`) instead of generic names like `"airflow"`
- [ ] Tune SQL specialist prompt to target specific tables mentioned in query instead of generating UNION ALL across all tables

## Future Work
- [ ] Add CodeFix specialist endpoint and wiring
- [ ] Add `maas_trace` visibility in frontend (show route, warehouse, specialist latency)
- [ ] Test repair loop end-to-end with a real SQL execution failure
- [ ] Run full test suite: `cd scanner && python -m pytest tests/copilot/maas/ -v`
