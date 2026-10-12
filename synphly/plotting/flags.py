"""
synphly.plotting.flags
======================
Flag-statistics plots (port of v0.5 helper_functions.plot_flag_stats,
calculate_percentages, plot_category_data) with an explicit plots_dir.

Output: {plots_dir}/flag_stats_{category}_flagged_data.jpg  (same names as
v0.5, where plots_dir was {working_directory}/plots).
"""

import os
import logging

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

log = logging.getLogger(__name__)

FLAG_CATEGORIES = ['field', 'observation', 'spw', 'correlation', 'antenna']


def calculate_percentages(data):
    """
    flagdata(mode='summary') dict -> {category: {item: flagged %}}.

    Items with total == 0 are skipped (v0.5 raised ZeroDivisionError).
    """
    percentages = {}
    for category, subcategories in data.items():
        if isinstance(subcategories, dict):
            percentages[category] = {}
            for subcategory, values in subcategories.items():
                if (isinstance(values, dict) and 'flagged' in values
                        and 'total' in values and values['total']):
                    percentages[category][subcategory] = (
                        values['flagged'] / values['total']) * 100
    return percentages


def plot_category_data(percentages_over_steps, category, plots_dir):
    """Flagged % per item of `category` across processing steps."""
    run_steps = list(percentages_over_steps.keys())
    if not all(category in step for step in percentages_over_steps.values()):
        log.warning("Category '%s' not found in all data steps.", category)
        return None

    subcategories = set()
    for step in percentages_over_steps.values():
        subcategories.update(step.get(category, {}).keys())

    fig = plt.figure(figsize=(10, 10))
    try:
        for subcategory in sorted(subcategories, key=str):
            flagged_percentages = [
                percentages_over_steps[step].get(category, {}).get(subcategory, 0)
                for step in run_steps]
            plt.plot(run_steps, flagged_percentages, label=subcategory, marker='o')
        plt.xlabel('Processing Step')
        plt.ylabel('Flagged Data (%)')
        plt.title(f'Flagged Data Over Processing Steps ({category.capitalize()})')
        plt.legend()
        plt.ylim(0, 100)
        plt.xticks(rotation=45)
        plt.tight_layout()
        os.makedirs(plots_dir, exist_ok=True)
        outfile = os.path.join(plots_dir, f'flag_stats_{category}_flagged_data.jpg')
        plt.savefig(outfile, dpi=300, bbox_inches='tight')
    finally:
        plt.close(fig)
    log.info("  Saved: %s", outfile)
    return outfile


def plot_flag_stats(flag_stats, plots_dir, categories=None):
    """
    flag_stats: {step_label: flagdata summary dict}.  One figure per category.
    Failures are logged as warnings.  Returns the written files.
    """
    percentages_over_steps = {label: calculate_percentages(step)
                              for label, step in flag_stats.items()}
    written = []
    for category in (categories or FLAG_CATEGORIES):
        try:
            out = plot_category_data(percentages_over_steps, category, plots_dir)
        except (RuntimeError, ValueError, TypeError, KeyError, OSError) as exc:
            log.warning("Flag-stat plot for '%s' failed: %s", category, exc)
            plt.close('all')
            continue
        if out:
            written.append(out)
    return written
