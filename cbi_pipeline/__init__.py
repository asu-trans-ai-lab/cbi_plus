"""
cbi_pipeline — a general-purpose CBI / FD / QVDF calibration package.

Handles both PeMS (speed + measured volume) and INRIX TMC (speed-only,
CBI inverse-S3 synthesizes volume) inputs through one unified pipeline.

Four explicit stages mirror the four layers in the canonical CBI codebase:
    Stage 1: speed-data QC                (stage1_qc.py)
    Stage 2: episode + day classification (stage2_episodes.py)
    Stage 3: robust regime-separated FD   (stage3_fd_robust.py)
    Stage 4: discharge-window mu          (stage4_mu_validation.py)

Stage 0 (io_unified.py) loads PeMS and INRIX TMC inputs into a common schema.
Stage 5 (stage5_qvdf.py + stage5_verification.py) runs the QVDF forward
model and round-by-round audit. diagnostics.py owns every figure.
run_pipeline.py and corridor_workflow.py are the CLI entry points.
"""

try:
    from importlib.metadata import version as _pkg_version
    __version__ = _pkg_version("cbi-plus")
except Exception:                    # source checkout without install
    __version__ = "2.11.0"
