from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Iterable, Optional


@dataclass(frozen=True)
class CleanupPlan:
    postgres_deleted: bool
    neo4j_deleted: bool
    milvus_deleted: bool


def _iter_non_empty(xs: Iterable[str]) -> list[str]:
    out: list[str] = []
    for x in xs:
        s = str(x or "").strip()
        if s:
            out.append(s)
    return out


def _cleanup_postgres(*, dry_run: bool) -> bool:
    """Delete all rows from GRAG tables in Postgres.

    This is destructive.
    """
    from grag.data_client import get_data_manager

    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                # Use DELETE (not TRUNCATE) to avoid requiring elevated privileges.
                # Order matters due to foreign key possibilities / logical dependencies.
                stmts = [
                    "DELETE FROM grag_relations",
                    "DELETE FROM grag_entities",
                    "DELETE FROM grag_chunks",
                    "DELETE FROM grag_documents",
                ]
                if dry_run:
                    for s in stmts:
                        print(f"[DRY-RUN][Postgres] would run: {s};")
                    return False

                for s in stmts:
                    try:
                        cur.execute(s)
                    except Exception as e:
                        # If a table doesn't exist in this environment, continue.
                        print(f"[Postgres] warn: failed to run {s}: {e}")
                return True
    finally:
        conn.close()


def _drop_and_recreate_postgres_schema(*, dry_run: bool) -> bool:
    """DROP GRAG tables in Postgres and recreate them.

    This is the most destructive option, intended to recover from schema drift.
    """
    from grag.data_client import get_data_manager
    from grag.storage.repositories.postgres_repository import PostgresGraphRepository

    dm = get_data_manager()
    conn = dm.get_postgres_client().get_connection()
    try:
        with conn:
            with conn.cursor() as cur:
                stmts = [
                    "DROP TABLE IF EXISTS grag_relations CASCADE",
                    "DROP TABLE IF EXISTS grag_entities CASCADE",
                    "DROP TABLE IF EXISTS grag_chunks CASCADE",
                    "DROP TABLE IF EXISTS grag_documents CASCADE",
                ]
                if dry_run:
                    for s in stmts:
                        print(f"[DRY-RUN][Postgres] would run: {s};")
                    print("[DRY-RUN][Postgres] would recreate schema via PostgresGraphRepository.ensure_schema()")
                    return False

                for s in stmts:
                    cur.execute(s)

        # Recreate schema (newest version)
        repo = PostgresGraphRepository(dm.get_postgres_client())
        repo.ensure_schema()
        print("[Postgres] dropped and recreated GRAG schema")
        return True
    finally:
        conn.close()


def _cleanup_neo4j(*, dry_run: bool) -> bool:
    """Delete all GRAG nodes/relationships in Neo4j.

    Current repo uses labels :Document, :Entity and relationship :REL.
    """
    from grag.data_client import get_data_manager

    dm = get_data_manager()
    driver = dm.get_neo4j_client().get_driver()

    db: Optional[str] = None
    try:
        db = dm.get_neo4j_client()._get_config().database
    except Exception:
        db = None

    # We delete by labels to avoid accidentally wiping a whole graph if user shares Neo4j.
    # If you have other labels, add them here explicitly.
    cypher_stmts = [
        "MATCH (e:Entity) DETACH DELETE e",
        "MATCH (d:Document) DETACH DELETE d",
    ]

    if dry_run:
        for c in cypher_stmts:
            print(f"[DRY-RUN][Neo4j] would run: {c}")
        return False

    def _run(tx):
        for c in cypher_stmts:
            tx.run(c)

    if db:
        with driver.session(database=db) as session:
            session.execute_write(_run)
    else:
        with driver.session() as session:
            session.execute_write(_run)

    return True


def _cleanup_milvus(*, collections: list[str], drop_collections: bool, dry_run: bool) -> bool:
    """Cleanup Milvus.

    You must either:
    - provide explicit --milvus-collections to delete rows from (safer), OR
    - pass --milvus-drop-all-collections to drop *all* collections (dangerous).
    """
    from grag.data_client import get_data_manager

    dm = get_data_manager()
    milvus = dm.get_milvus_client()
    milvus.connect()
    pymilvus = __import__("pymilvus")

    if drop_collections:
        # DANGEROUS: will drop all collections in the connected Milvus.
        names = list(pymilvus.utility.list_collections(using=milvus._alias))
        if dry_run:
            print(f"[DRY-RUN][Milvus] would drop collections: {names}")
            return False
        for name in names:
            try:
                pymilvus.utility.drop_collection(name, using=milvus._alias)
                print(f"[Milvus] dropped collection: {name}")
            except Exception as e:
                print(f"[Milvus] warn: failed to drop collection {name}: {e}")
        return True

    if not collections:
        print("[Milvus] skip: no --milvus-collections provided and --milvus-drop-all-collections not set")
        return False

    changed = False
    for name in collections:
        if dry_run:
            print(f"[DRY-RUN][Milvus] would delete all rows from collection: {name}")
            continue

        try:
            if not pymilvus.utility.has_collection(name, using=milvus._alias):
                print(f"[Milvus] warn: collection not found: {name}")
                continue

            col = pymilvus.Collection(name=name, using=milvus._alias)

            # Delete everything. (expr must be valid; we rely on pk being a primary field.)
            # In Milvus, a common trick is to delete by an always-true predicate.
            # For varchars, `pk != ""` is generally valid.
            try:
                col.delete('pk != ""')
            except Exception:
                # Fallback: if pk isn't called pk, user should pass drop_all_collections.
                col.delete('group_id != ""')
            col.flush()
            print(f"[Milvus] deleted all rows from collection: {name}")
            changed = True
        except Exception as e:
            print(f"[Milvus] warn: failed to cleanup collection {name}: {e}")

    return changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Dangerous cleanup script: delete GRAG data from Postgres/Neo4j/Milvus. "
            "Defaults to --dry-run. Use --yes to actually execute."
        )
    )
    parser.add_argument("--yes", action="store_true", help="Actually execute deletions (required).")
    parser.add_argument("--dry-run", action="store_true", help="Print operations without executing.")

    parser.add_argument("--postgres", action="store_true", help="Cleanup Postgres GRAG tables.")
    parser.add_argument(
        "--postgres-drop-tables",
        action="store_true",
        help="DANGEROUS: drop GRAG tables in Postgres and recreate schema (fixes schema drift).",
    )
    parser.add_argument("--neo4j", action="store_true", help="Cleanup Neo4j GRAG nodes.")
    parser.add_argument(
        "--milvus",
        action="store_true",
        help="Cleanup Milvus collections (requires --milvus-collections or --milvus-drop-all-collections).",
    )
    parser.add_argument(
        "--milvus-collections",
        nargs="*",
        default=[],
        help=(
            "Milvus collection names to cleanup (delete all rows). Example: --milvus-collections c1 c2. "
            "Safer than dropping all collections."
        ),
    )
    parser.add_argument(
        "--milvus-drop-all-collections",
        action="store_true",
        help="DANGEROUS: drop ALL collections in Milvus (ignores --milvus-collections).",
    )

    args = parser.parse_args()

    dry_run = bool(args.dry_run) or (not bool(args.yes))

    if not (args.postgres or args.neo4j or args.milvus):
        # Default to cleaning everything (still gated by --yes)
        args.postgres = True
        args.neo4j = True
        args.milvus = True

    # Initialize config before creating clients.
    from grag.config import get_config_manager

    get_config_manager().initialize()

    plan = CleanupPlan(postgres_deleted=False, neo4j_deleted=False, milvus_deleted=False)

    postgres_deleted = False
    neo4j_deleted = False
    milvus_deleted = False

    if args.postgres or args.postgres_drop_tables:
        if args.postgres_drop_tables:
            postgres_deleted = _drop_and_recreate_postgres_schema(dry_run=dry_run)
        else:
            postgres_deleted = _cleanup_postgres(dry_run=dry_run)

    if args.neo4j:
        neo4j_deleted = _cleanup_neo4j(dry_run=dry_run)

    if args.milvus:
        milvus_deleted = _cleanup_milvus(
            collections=_iter_non_empty(args.milvus_collections),
            drop_collections=bool(args.milvus_drop_all_collections),
            dry_run=dry_run,
        )

    plan = CleanupPlan(
        postgres_deleted=postgres_deleted,
        neo4j_deleted=neo4j_deleted,
        milvus_deleted=milvus_deleted,
    )

    print("\n[Cleanup summary]")
    print(plan)

    if dry_run:
        print("\nNOTE: This was a dry-run. Re-run with --yes to actually delete data.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
