import argparse
import sys


def main(config_path, predictions_path=None):

    print("=========================================================================")
    print("🚀 Starting Experiment Analysis Wrapper")
    print("=========================================================================")

    # 1. Run ML Evaluation
    print("\n📊 [Step 1/2] Running ML Evaluation...")
    import run_ml_evaluation
    try:
        run_ml_evaluation.main(config_path, predictions_path)
    except Exception as e:
        print(f"❌ ML Evaluation failed: {e}")
        sys.exit(1)

    # 2. Run Backtest
    print("\n📈 [Step 2/2] Running Backtest Simulation...")
    import run_backtest
    try:
        run_backtest.main(config_path, predictions_path)
    except Exception as e:
        print(f"❌ Backtest failed: {e}")
        sys.exit(1)

    print("\n=========================================================================")
    print("🎉 All analyses completed successfully!")
    print("=========================================================================")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, required=True, help="Path to config yaml")
    parser.add_argument(
        "--predictions-path",
        type=str,
        default=None,
        help="Path to pre-computed predictions parquet file",
    )
    args = parser.parse_args()
    main(args.config, args.predictions_path)
