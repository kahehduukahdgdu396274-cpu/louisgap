from core.worker_gate_adapter import authorize_worker_write
def main():
    try:
        authorize_worker_write()
        print(
            "WORKER_GATE_ADAPTER PASS"
        )
    except Exception as e:
        print(
            "WORKER_GATE_ADAPTER FAIL",
            e
        )
if __name__ == "__main__":
    main()
