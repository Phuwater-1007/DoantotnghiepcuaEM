"""Export the training history embedded in an Ultralytics YOLO checkpoint."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from ultralytics import YOLO


DEFAULT_MODEL = Path("data/models/char_detector_yolo11.pt")
DEFAULT_OUTPUT = Path("training_history_recovered/char_yolo11s_v2")


def _best_epoch(results: dict[str, list[float]], metric: str) -> tuple[int, int]:
    values = results[metric]
    index = max(range(len(values)), key=values.__getitem__)
    return index, int(results["epoch"][index])


def _metric_at(results: dict[str, list[float]], metric: str, index: int) -> float:
    return float(results[metric][index])


def export_history(model_path: Path, output_dir: Path) -> None:
    checkpoint = YOLO(str(model_path)).ckpt or {}
    results = checkpoint.get("train_results")
    if not isinstance(results, dict) or not results.get("epoch"):
        raise RuntimeError(f"Checkpoint does not contain per-epoch training results: {model_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    train_args = checkpoint.get("train_args") or {}
    run_name = train_args.get("name") or model_path.stem

    columns = list(results)
    row_count = len(results["epoch"])
    csv_path = output_dir / "results.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(columns)
        for row_index in range(row_count):
            writer.writerow([results[column][row_index] for column in columns])

    best_index, best_epoch = _best_epoch(results, "metrics/mAP50-95(B)")
    final_index = row_count - 1
    total_seconds = float(results["time"][-1])
    completed_at_text = checkpoint.get("date")
    started_at_inferred = None
    if completed_at_text:
        completed_at = datetime.fromisoformat(completed_at_text)
        started_at_inferred = (completed_at - timedelta(seconds=total_seconds)).isoformat()

    metric_names = [
        "metrics/precision(B)",
        "metrics/recall(B)",
        "metrics/mAP50(B)",
        "metrics/mAP50-95(B)",
        "val/box_loss",
        "val/cls_loss",
        "val/dfl_loss",
    ]
    summary = {
        "source_checkpoint": str(model_path.resolve()),
        "ultralytics_version": checkpoint.get("version"),
        "checkpoint_date": completed_at_text,
        "training_start_inferred": started_at_inferred,
        "total_training_seconds": total_seconds,
        "total_training_hms": str(timedelta(seconds=round(total_seconds))),
        "epochs_completed": row_count,
        "best_epoch_by_map50_95": best_epoch,
        "best_epoch_metrics": {
            name: _metric_at(results, name, best_index) for name in metric_names
        },
        "final_epoch_metrics": {
            name: _metric_at(results, name, final_index) for name in metric_names
        },
        "checkpoint_train_metrics": checkpoint.get("train_metrics"),
        "train_args": train_args,
    }
    json_path = output_dir / "training_summary.json"
    json_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    import matplotlib.pyplot as plt

    epochs = results["epoch"]
    figure, axes = plt.subplots(2, 2, figsize=(14, 9))

    for key in ("train/box_loss", "train/cls_loss", "train/dfl_loss"):
        axes[0, 0].plot(epochs, results[key], label=key.removeprefix("train/"))
    axes[0, 0].set_title("Training losses")

    for key in ("val/box_loss", "val/cls_loss", "val/dfl_loss"):
        axes[0, 1].plot(epochs, results[key], label=key.removeprefix("val/"))
    axes[0, 1].set_title("Validation losses")

    for key in (
        "metrics/precision(B)",
        "metrics/recall(B)",
        "metrics/mAP50(B)",
        "metrics/mAP50-95(B)",
    ):
        axes[1, 0].plot(epochs, results[key], label=key.removeprefix("metrics/").removesuffix("(B)"))
    axes[1, 0].axvline(best_epoch, color="black", linestyle="--", alpha=0.5, label=f"best epoch {best_epoch}")
    axes[1, 0].set_title("Validation metrics")

    lr_columns = [column for column in columns if column.startswith("lr/")]
    for key in lr_columns:
        axes[1, 1].plot(epochs, results[key], label=key.removeprefix("lr/"), alpha=0.75)
    axes[1, 1].set_title("Learning rates")

    for axis in axes.flat:
        axis.set_xlabel("Epoch")
        axis.grid(alpha=0.25)
        axis.legend(fontsize=8)

    figure.suptitle(f"Recovered YOLO training history - {run_name}")
    figure.tight_layout()
    plot_path = output_dir / "results.png"
    figure.savefig(plot_path, dpi=180, bbox_inches="tight")
    plt.close(figure)

    report_path = output_dir / "TRAINING_REPORT.md"
    best = summary["best_epoch_metrics"]
    final = summary["final_epoch_metrics"]
    report_path.write_text(
        "\n".join(
            [
                "# Recovered training report",
                "",
                f"- Run name: `{run_name}`",
                f"- Checkpoint date: `{completed_at_text}`",
                f"- Inferred start time: `{started_at_inferred}`",
                f"- Training time: `{summary['total_training_hms']}` ({total_seconds:.2f} seconds)",
                f"- Completed epochs: `{row_count}`",
                f"- Best epoch by mAP50-95: `{best_epoch}`",
                f"- Dataset: `{summary['train_args'].get('data')}`",
                f"- Base model: `{summary['train_args'].get('model')}`",
                "",
                "| Metric | Best epoch | Final epoch |",
                "|---|---:|---:|",
                f"| Precision | {best['metrics/precision(B)']:.5f} | {final['metrics/precision(B)']:.5f} |",
                f"| Recall | {best['metrics/recall(B)']:.5f} | {final['metrics/recall(B)']:.5f} |",
                f"| mAP50 | {best['metrics/mAP50(B)']:.5f} | {final['metrics/mAP50(B)']:.5f} |",
                f"| mAP50-95 | {best['metrics/mAP50-95(B)']:.5f} | {final['metrics/mAP50-95(B)']:.5f} |",
                f"| Validation box loss | {best['val/box_loss']:.5f} | {final['val/box_loss']:.5f} |",
                f"| Validation class loss | {best['val/cls_loss']:.5f} | {final['val/cls_loss']:.5f} |",
                f"| Validation DFL loss | {best['val/dfl_loss']:.5f} | {final['val/dfl_loss']:.5f} |",
                "",
                "> The start time is inferred by subtracting the cumulative training time from the checkpoint date.",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"Exported {row_count} epochs to {output_dir.resolve()}")
    print(f"Best epoch: {best_epoch}; mAP50-95: {best['metrics/mAP50-95(B)']:.5f}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    export_history(args.model, args.output)


if __name__ == "__main__":
    main()
