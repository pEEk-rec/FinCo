"""
CLI entrypoint.
"""
import argparse
import uuid

from copilot.agent.loop import run_turn
from copilot.db.connection import get_connection, init_db
from copilot.governance.policy import load_policy
from copilot.tools.executor import ExecutionContext
from copilot.tools.financial import register_financial_tools
from copilot.tools.registry import register


def main():
    parser = argparse.ArgumentParser(description="Finance Copilot CLI")
    parser.add_argument("--db", default=":memory:", help="Database path")
    parser.add_argument("--policy", default="config/policy.yaml", help="Policy path")
    parser.add_argument("--user", default="default_user", help="User ID")
    args = parser.parse_args()

    conn = get_connection(args.db)
    init_db(conn)
    
    conn.execute(
        "INSERT OR IGNORE INTO users (id, created_at) VALUES (?, '2023-01-01T00:00:00Z')", 
        (args.user,)
    )
    conn.commit()

    policy = load_policy(args.policy)
    run_id = str(uuid.uuid4())
    
    ctx = ExecutionContext(conn=conn, user_id=args.user, run_id=run_id, policy=policy)
    
    register_financial_tools(register)
    
    print("Welcome to Finance Copilot (Phase 0).")
    print("Type 'exit' or 'quit' to exit.")
    
    last_msg = ""
    while True:
        try:
            user_input = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
            
        if user_input.lower() in ["exit", "quit"]:
            break
            
        approved = False
        if user_input.lower() in ["yes", "y", "approve"] and last_msg:
            approved = True
            user_input = last_msg
        else:
            last_msg = user_input
            
        response = run_turn(ctx, user_input, approved=approved)
        print(response)

if __name__ == "__main__":
    main()
