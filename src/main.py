"""
main.py : 一键演示 / 数据初始化
================================
用法：
  python main.py build            # 生成虚拟数据 + 建库
  python main.py review C001      # 对 C001 跑本周复盘
  python main.py eval             # 跑全量自测
"""
import os
import sys
import sqlite3

HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "..", "data", "adpilot.db")

sys.path.insert(0, HERE)
import mock_data
import db as dbm
from weekly_review import run_weekly_review
from llm import get_llm


def build():
    store = mock_data.generate_raw_dataset()
    conn = dbm.init_db(DB_PATH)
    dbm.load_from_store(conn, store)
    dbm.load_derived(conn)   # 预警 / 待办 / Badcase 三张派生表
    print(f"已生成并入库："
          f"客户 {len(store['customers'])} / "
          f"广告 {len(store['xhs_ads'])+len(store['douyin_ads'])+len(store['tencent_ads'])+len(store['kuaishou_ads'])} / "
          f"笔记 {len(store['xhs_notes'])} / 沟通 {len(store['wecom'])} / 大盘 {len(store['benchmarks'])}")
    na = conn.execute("SELECT COUNT(*) FROM alerts").fetchone()[0]
    nt = conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    nb = conn.execute("SELECT COUNT(*) FROM badcases").fetchone()[0]
    print(f"派生表：预警 {na} / 待办 {nt} / Badcase {nb}")
    conn.close()


def review(cid: str):
    if not os.path.exists(DB_PATH):
        build()
    conn = dbm.init_db(DB_PATH)
    period = dbm.latest_period(conn)
    r = run_weekly_review(conn, cid, period, get_llm())
    print(r.render())
    conn.close()


def ev():
    if not os.path.exists(DB_PATH):
        build()
    from eval_review import evaluate
    res = evaluate(DB_PATH)
    print(f"通过率 {res['passed']}/{res['total']} = {res['pass_rate']}%")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    if cmd == "build":
        build()
    elif cmd == "review":
        review(sys.argv[2] if len(sys.argv) > 2 else "C001")
    elif cmd == "eval":
        ev()
    else:
        print(__doc__)
