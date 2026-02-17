import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from test.grag.storage.test_milvus_repository import run_tests as run_milvus_repo_tests
from test.grag.storage.test_neo4j_repository import run_tests as run_neo4j_repo_tests
from test.grag.storage.test_postgres_repository import run_tests as run_postgres_repo_tests
from test.grag.storage.test_storage_impl import run_tests as run_storage_impl_tests


def run_tests() -> None:
    print("\n" + "=" * 60)
    print("开始运行 storage 测试套件")
    print("注意：该测试套件默认真实连接数据库，并可能创建表/collection/constraint；测试结束会清理写入数据")
    print("=" * 60)

    run_postgres_repo_tests()
    run_neo4j_repo_tests()
    run_milvus_repo_tests()
    run_storage_impl_tests()


if __name__ == "__main__":
    run_tests()
