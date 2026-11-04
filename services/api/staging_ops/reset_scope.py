"""
Reset scope: what a staging reset may remove, and proof that nothing else moved.

What:
    Catalog SQL and a transaction routine that remove the application-owned
    objects of schema `public` and nothing outside that scope.

Why:
    `DROP ... CASCADE` follows dependencies into other schemas (views, foreign
    keys, triggers, policies, columns typed by a public enum), so a cascade can
    silently destroy objects the reset was never authorized to touch. The
    invariant enforced here is:

        A staging reset never modifies or drops an object outside its
        explicitly authorized scope.

    The scope is "objects in schema `public` that no extension owns". Four
    independent layers uphold the invariant, so a gap in one is not enough:

    1. Preflight (`EXTERNAL_DEPENDENTS_SQL`) lists every object outside the
       scope that depends on a scoped object, and the reset is refused.
    2. Every DROP is explicit and RESTRICT (the PostgreSQL default is spelled
       out): PostgreSQL itself refuses to drop an object that still has a
       dependent which is not named in the same statement.
    3. The same dependency check is repeated inside the destroying transaction
       after ACCESS EXCLUSIVE locks are taken on the scoped tables, so DDL that
       would add a dependent (a partition, a statistics object, a foreign key)
       must wait for the transaction or fail.
    4. A fingerprint of every out-of-scope catalog definition is taken before
       and after the drops; the transaction commits only if it is identical.
       This catches dependency kinds that RESTRICT does not enforce
       (PostgreSQL drops automatic dependents such as partitions and extended
       statistics even under RESTRICT).

    What is deliberately NOT protected: privileges granted on a scoped object
    disappear with it, and outbound references (a scoped table's foreign key
    to an out-of-scope table) are removed with the scoped table. The
    out-of-scope table, its definition and its rows are unchanged; only
    PostgreSQL's internal foreign-key trigger rows on it are not compared.
"""

from typing import List, Tuple

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from staging_ops.errors import StagingRefused

# Passes over the drop list. Each pass removes every object that no longer has
# a remaining dependent; a pass without progress means a dependency cycle or a
# blocker, and the reset is refused instead of falling back to CASCADE.
MAX_DROP_PASSES = 8

# SQLSTATE of "cannot drop X because other objects depend on it".
DEPENDENT_OBJECTS_STILL_EXIST = "2BP01"

# Objects in the scope. A scoped relation/function/type lives in `public` and
# is not a member of an extension.
SCOPE_CTES = """
scope_rel AS (
  SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public'
     AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
),
scope_proc AS (
  SELECT p.oid FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'public'
     AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype = 'e')
),
scope_type AS (
  SELECT t.oid FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
   WHERE n.nspname = 'public'
     AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
),
scope_stat AS (
  SELECT s.oid FROM pg_statistic_ext s JOIN pg_namespace n ON n.oid = s.stxnamespace
   WHERE n.nspname = 'public'
)
"""

# Every object outside the scope that depends on an object inside it.
# A dependency class this query cannot attribute to a scoped owner is reported
# too (fail closed). TOAST tables are internal parts of their owner.
EXTERNAL_DEPENDENTS_SQL = f"""
WITH {SCOPE_CTES}
SELECT pg_describe_object(d.classid, d.objid, d.objsubid) AS dependent,
       pg_describe_object(d.refclassid, d.refobjid, d.refobjsubid) AS referenced
  FROM pg_depend d
 WHERE d.deptype NOT IN ('e', 'p')
   AND (   (d.refclassid = 'pg_class'::regclass AND d.refobjid IN (SELECT oid FROM scope_rel))
        OR (d.refclassid = 'pg_proc'::regclass  AND d.refobjid IN (SELECT oid FROM scope_proc))
        OR (d.refclassid = 'pg_type'::regclass  AND d.refobjid IN (SELECT oid FROM scope_type)))
   AND NOT (
        CASE d.classid
          WHEN 'pg_class'::regclass THEN d.objid IN (SELECT oid FROM scope_rel)
                                         OR EXISTS (SELECT 1 FROM pg_class t WHERE t.oid = d.objid AND t.relkind = 't')
          WHEN 'pg_proc'::regclass  THEN d.objid IN (SELECT oid FROM scope_proc)
          WHEN 'pg_type'::regclass  THEN d.objid IN (SELECT oid FROM scope_type)
          WHEN 'pg_constraint'::regclass THEN EXISTS (
            SELECT 1 FROM pg_constraint k WHERE k.oid = d.objid
               AND (k.conrelid IN (SELECT oid FROM scope_rel) OR k.contypid IN (SELECT oid FROM scope_type)))
          WHEN 'pg_trigger'::regclass THEN EXISTS (SELECT 1 FROM pg_trigger g WHERE g.oid = d.objid AND g.tgrelid IN (SELECT oid FROM scope_rel))
          WHEN 'pg_rewrite'::regclass THEN EXISTS (SELECT 1 FROM pg_rewrite w WHERE w.oid = d.objid AND w.ev_class IN (SELECT oid FROM scope_rel))
          WHEN 'pg_attrdef'::regclass THEN EXISTS (SELECT 1 FROM pg_attrdef a WHERE a.oid = d.objid AND a.adrelid IN (SELECT oid FROM scope_rel))
          WHEN 'pg_policy'::regclass  THEN EXISTS (SELECT 1 FROM pg_policy y WHERE y.oid = d.objid AND y.polrelid IN (SELECT oid FROM scope_rel))
          WHEN 'pg_statistic_ext'::regclass THEN d.objid IN (SELECT oid FROM scope_stat)
          -- Implicit casts PostgreSQL creates with a range type (range -> multirange) die with the type.
          WHEN 'pg_cast'::regclass THEN d.deptype IN ('a', 'i') AND EXISTS (
            SELECT 1 FROM pg_cast x WHERE x.oid = d.objid
               AND x.castsource IN (SELECT oid FROM scope_type) AND x.casttarget IN (SELECT oid FROM scope_type))
          ELSE false
        END)
 ORDER BY 1, 2
"""

# Relations, functions and types that are NOT in the scope; used by the fingerprint.
OUTSIDE_CTES = f"""
{SCOPE_CTES},
outside_rel AS (
  SELECT c.oid FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE c.oid NOT IN (SELECT oid FROM scope_rel)
     AND c.relpersistence <> 't'
     AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast') AND n.nspname NOT LIKE 'pg\\_temp\\_%' AND n.nspname NOT LIKE 'pg\\_toast\\_temp\\_%'
)
"""

# One digest of every out-of-scope catalog definition a cascade could change.
# Internal foreign-key triggers are excluded (see the module docstring); every
# other trigger, constraint, column, default, policy, rule, inheritance link,
# statistics object, function and type outside the scope is included.
FINGERPRINT_SQL = f"""
WITH {OUTSIDE_CTES}
SELECT md5(string_agg(line, E'\\n' ORDER BY line)) FROM (
  SELECT concat_ws('|', 'rel', c.oid, c.relnamespace, c.relname, c.relkind) AS line
    FROM pg_class c WHERE c.oid IN (SELECT oid FROM outside_rel)
  UNION ALL
  SELECT concat_ws('|', 'col', a.attrelid, a.attnum, a.attname, a.atttypid, a.attisdropped, a.attnotnull)
    FROM pg_attribute a WHERE a.attrelid IN (SELECT oid FROM outside_rel)
  UNION ALL
  SELECT concat_ws('|', 'con', k.oid, k.conname, k.contype, k.conrelid, k.confrelid, k.contypid, coalesce(k.conkey::text, '~'), coalesce(k.confkey::text, '~'))
    FROM pg_constraint k WHERE k.conrelid IN (SELECT oid FROM outside_rel)
  UNION ALL
  SELECT concat_ws('|', 'trg', g.oid, g.tgrelid, g.tgname, g.tgfoid, g.tgenabled)
    FROM pg_trigger g WHERE g.tgrelid IN (SELECT oid FROM outside_rel) AND NOT g.tgisinternal
  UNION ALL
  SELECT concat_ws('|', 'pol', y.oid, y.polrelid, y.polname, y.polcmd)
    FROM pg_policy y WHERE y.polrelid IN (SELECT oid FROM outside_rel)
  UNION ALL
  SELECT concat_ws('|', 'rule', w.oid, w.ev_class, w.rulename)
    FROM pg_rewrite w WHERE w.ev_class IN (SELECT oid FROM outside_rel)
  UNION ALL
  SELECT concat_ws('|', 'def', a.oid, a.adrelid, a.adnum)
    FROM pg_attrdef a WHERE a.adrelid IN (SELECT oid FROM outside_rel)
  UNION ALL
  SELECT concat_ws('|', 'inh', i.inhrelid, i.inhparent, i.inhseqno)
    FROM pg_inherits i WHERE i.inhrelid IN (SELECT oid FROM outside_rel) OR i.inhparent IN (SELECT oid FROM outside_rel)
  UNION ALL
  SELECT concat_ws('|', 'stat', s.oid, s.stxnamespace, s.stxname, s.stxrelid)
    FROM pg_statistic_ext s WHERE s.oid NOT IN (SELECT oid FROM scope_stat)
  UNION ALL
  SELECT concat_ws('|', 'proc', p.oid, p.pronamespace, p.proname, md5(coalesce(p.prosrc, '')))
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE p.oid NOT IN (SELECT oid FROM scope_proc) AND n.nspname NOT IN ('pg_catalog', 'information_schema')
  UNION ALL
  SELECT concat_ws('|', 'type', t.oid, t.typnamespace, t.typname, t.typtype)
    FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
   WHERE t.oid NOT IN (SELECT oid FROM scope_type) AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
     AND n.nspname NOT LIKE 'pg\\_temp\\_%' AND n.nspname NOT LIKE 'pg\\_toast\\_temp\\_%'
) fingerprint
"""

# Scoped objects to remove, with the DROP kind and a fully quoted, schema
# qualified name. Functions carry their identity arguments.
SCOPE_OBJECTS_SQL = """
SELECT kind, name FROM (
  SELECT CASE c.relkind WHEN 'v' THEN 'VIEW' WHEN 'm' THEN 'MATERIALIZED VIEW' WHEN 'f' THEN 'FOREIGN TABLE'
                        WHEN 'S' THEN 'SEQUENCE' WHEN 'c' THEN 'TYPE' ELSE 'TABLE' END AS kind,
         format('%I.%I', n.nspname, c.relname) AS name
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
   WHERE n.nspname = 'public' AND c.relkind IN ('r','p','v','m','f','S','c')
     AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype IN ('e', 'a', 'i')
                       AND (d.deptype = 'e' OR (c.relkind = 'S' AND d.refclassid = 'pg_class'::regclass)))
  UNION ALL
  SELECT CASE p.prokind WHEN 'p' THEN 'PROCEDURE' WHEN 'a' THEN 'AGGREGATE' ELSE 'FUNCTION' END,
         format('%I.%I(%s)', n.nspname, p.proname,
                CASE WHEN p.prokind = 'a' AND pg_get_function_identity_arguments(p.oid) = '' THEN '*'
                     ELSE pg_get_function_identity_arguments(p.oid) END)
    FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
   WHERE n.nspname = 'public'
     AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_proc'::regclass AND d.objid = p.oid AND d.deptype IN ('e', 'i'))
  UNION ALL
  SELECT 'TYPE', format('%I.%I', n.nspname, t.typname)
    FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
   WHERE n.nspname = 'public' AND t.typtype IN ('e','d','r')
     AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_type'::regclass AND d.objid = t.oid AND d.deptype = 'e')
) objects ORDER BY kind, name
"""

# Statements are built per pass in this order; each kind is attempted as one
# multi-object statement (so mutual foreign keys drop together) and, if
# PostgreSQL reports a remaining dependent, object by object.
DROP_ORDER = (
    "VIEW", "MATERIALIZED VIEW", "FOREIGN TABLE", "TABLE", "SEQUENCE",
    "FUNCTION", "PROCEDURE", "AGGREGATE", "TYPE",
)

# Relations that carry an ACCESS EXCLUSIVE lock for the whole transaction.
LOCKABLE_SQL = """
SELECT format('%I.%I', n.nspname, c.relname)
  FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
   AND NOT EXISTS (SELECT 1 FROM pg_depend d WHERE d.classid = 'pg_class'::regclass AND d.objid = c.oid AND d.deptype = 'e')
 ORDER BY 1
"""


def _statement(text_value: str) -> str:
    # Object names are data; a literal % must not be read as a driver placeholder
    # (exec_driver_sql hands the string to the driver unchanged).
    return text_value.replace("%", "%%")


# Reads the out-of-scope objects that depend on scoped objects.
# Parameters:
# - connection: any SQLAlchemy connection (read-only is enough).
# Returns:
# - (dependent description, referenced description) pairs; empty when the reset is boundary-safe.
def external_dependents(connection) -> List[Tuple[str, str]]:
    return [(str(row[0]), str(row[1])) for row in connection.execute(text(EXTERNAL_DEPENDENTS_SQL))]


# Reads the digest of every out-of-scope catalog definition.
def outside_fingerprint(connection) -> str:
    return str(connection.execute(text(FINGERPRINT_SQL)).scalar())


def _try_drop(connection, kind: str, names: List[str]) -> bool:
    statement = f"DROP {kind} IF EXISTS {', '.join(names)} RESTRICT"
    nested = connection.begin_nested()

    try:
        connection.exec_driver_sql(_statement(statement))
    except DBAPIError as error:
        nested.rollback()

        if getattr(error.orig, "pgcode", None) == DEPENDENT_OBJECTS_STILL_EXIST:
            return False

        raise

    nested.commit()

    return True


# Removes every scoped object inside the caller's transaction, RESTRICT only.
# Preconditions held by the caller: advisory lock taken, identity verified.
# Parameters:
# - connection: connection of the open transaction.
# Returns:
# - Number of objects dropped.
# Raises:
# - StagingRefused: EXTERNAL_DEPENDENCIES, EXTERNAL_OBJECT_CHANGED,
#   RESET_BLOCKED, RESET_INCOMPLETE. The caller rolls the transaction back.
def drop_scope(connection) -> int:
    for relation in [row[0] for row in connection.execute(text(LOCKABLE_SQL))]:
        connection.exec_driver_sql(_statement(f"LOCK TABLE {relation} IN ACCESS EXCLUSIVE MODE"))

    if external_dependents(connection):
        raise StagingRefused("EXTERNAL_DEPENDENCIES", "objects outside schema public depend on application objects; nothing was changed")

    before = outside_fingerprint(connection)
    remaining = [(row[0], row[1]) for row in connection.execute(text(SCOPE_OBJECTS_SQL))]
    dropped = 0

    for _pass in range(MAX_DROP_PASSES):
        if not remaining:
            break

        progressed = False

        for kind in DROP_ORDER:
            names = [name for object_kind, name in remaining if object_kind == kind]

            if not names:
                continue

            if _try_drop(connection, kind, names):
                done = set(names)
            else:
                done = {name for name in names if _try_drop(connection, kind, [name])}

            if done:
                progressed = True
                dropped += len(done)
                remaining = [(object_kind, name) for object_kind, name in remaining if not (object_kind == kind and name in done)]

        if not progressed:
            break

    if remaining:
        raise StagingRefused("RESET_BLOCKED", "some application objects could not be dropped without cascading; nothing was changed")

    if outside_fingerprint(connection) != before:
        raise StagingRefused("EXTERNAL_OBJECT_CHANGED", "the reset would have changed objects outside schema public; nothing was changed")

    return dropped
