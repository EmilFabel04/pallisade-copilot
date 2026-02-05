"""Looker knowledge articles."""

from .. import KnowledgeArticle, KnowledgeCategory

LOOKER_ARTICLES = [
    KnowledgeArticle(
        id="looker-pdt-failures",
        title="Fixing Looker PDT Build Failures",
        category=KnowledgeCategory.TROUBLESHOOTING,
        tags=["looker", "pdt", "persistent-derived-table", "rebuild", "cache", "failure"],
        tools=["LOOKER"],
        summary="How to debug and fix Looker Persistent Derived Table (PDT) build failures: SQL errors, timeouts, and trigger issues.",
        content="""## Fixing Looker PDT Build Failures

### What Are PDTs?
Persistent Derived Tables are materialized tables Looker builds and caches in your warehouse.
They rebuild on a schedule (trigger) or when source data changes.

### Debugging Workflow
1. Admin → Persistent Derived Tables → Find the failed PDT
2. Check the **SQL error** message
3. Run the PDT SQL manually in your warehouse for detailed errors

### Common Failures

**SQL Error**
- The derived table query has a syntax error or references missing columns
- Fix: Copy the SQL from LookML, run in warehouse, fix the error

**Timeout**
- PDT query takes too long to build
- Fix: Optimize the query, add indexes/clustering on source tables, increase warehouse timeout

**Trigger Issues**
- `sql_trigger_value` returns same value → PDT doesn't rebuild
- Fix: Use `SELECT MAX(updated_at)` or `SELECT CURRENT_DATE` as trigger
- Check: Admin → PDTs → Trigger value column

**Permission Error**
- Looker connection lacks CREATE TABLE permissions in scratch schema
- Fix: Grant Looker database user write access to the PDT schema

### Best Practices
- Use `datagroup` triggers for coordinated rebuilds (all related PDTs rebuild together)
- Set reasonable `max_cache_age` as a fallback
- Monitor PDT build times — investigate if they grow
""",
    ),
    KnowledgeArticle(
        id="looker-lookml-best-practices",
        title="LookML Best Practices",
        category=KnowledgeCategory.BEST_PRACTICES,
        tags=["looker", "lookml", "model", "explore", "dimension", "measure"],
        tools=["LOOKER"],
        summary="LookML best practices: model organization, explore design, dimension/measure naming, and performance optimization.",
        content="""## LookML Best Practices

### Model Organization
- One model per business domain (e.g., `ecommerce.model`, `marketing.model`)
- One view per source table or dbt model
- Use `extends` for shared dimension/measure sets

### Naming Conventions
- **Views**: Match source table name (`orders`, `customers`)
- **Dimensions**: Descriptive, lowercase_snake: `order_status`, `customer_name`
- **Measures**: Verb + noun: `total_revenue`, `count_orders`, `avg_order_value`
- **Explores**: Business-friendly names: `Order Analysis`, `Customer Segments`

### Explore Design
- Start with the most granular fact table
- Join dimensions using `relationship: many_to_one`
- Always specify `relationship` parameter (Looker defaults to `many_to_one`)
- Use `fields` parameter to hide unnecessary columns from users

### Performance
- Use PDTs for expensive joins/aggregations
- Add `indexes` to PDTs for common filter columns
- Use `aggregate_awareness` for pre-aggregated tables
- Set `persist_for` or `sql_trigger_value` on derived tables

### Access Control
- Use `access_grant` for row-level security
- Use `hidden: yes` on sensitive dimensions
- Create separate models per team with appropriate access
""",
    ),
]
