"""forge-audit -- the proof-tool: run the quality gates on a repo, emit a JSON scorecard.

It *proves* the "engineer-who-uses-AI-as-a-force-multiplier" thesis instead of asserting
it, by grading any repo against objective stage thresholds behind a mockable GitHub seam.
"""

from forge_audit.scorecard import Scorecard, build_scorecard

__all__ = ["Scorecard", "build_scorecard"]
__version__ = "0.1.0"
