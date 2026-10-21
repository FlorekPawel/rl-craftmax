"""Gameplay and training videos: rollouts, frames, review, ffmpeg cuts.

Shared building blocks: ``ffmpeg`` (encoding), ``text`` (captions), ``rollout``
(record and replay). Gameplay steps: ``render``, ``review``, ``cuts``.
Learning-process steps: ``eval_rollouts``, ``overlay``. Each step runs as
``python -m wut_murl_craftax.visualisation.<step>``.
"""

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # real names for type checkers; runtime imports stay lazy
    from .cuts import gif, long_cut, short_cut
    from .eval_rollouts import (
        EvalRun,
        evaluate,
        evaluate_spec,
        load_eval,
        network_outputs,
        replay_episode,
    )
    from .overlay import render_overlay
    from .render import render_kept, render_master
    from .review import build_assets, write_page
    from .rollout import (
        HeuristicPolicy,
        NetworkPolicy,
        Policy,
        RandomPolicy,
        Rollout,
        game_for,
        play,
        replay,
    )

_EXPORTS: dict[str, str] = {
    "EvalRun": "eval_rollouts",
    "HeuristicPolicy": "rollout",
    "NetworkPolicy": "rollout",
    "Policy": "rollout",
    "RandomPolicy": "rollout",
    "Rollout": "rollout",
    "build_assets": "review",
    "evaluate": "eval_rollouts",
    "evaluate_spec": "eval_rollouts",
    "game_for": "rollout",
    "gif": "cuts",
    "load_eval": "eval_rollouts",
    "long_cut": "cuts",
    "network_outputs": "eval_rollouts",
    "play": "rollout",
    "render_kept": "render",
    "render_master": "render",
    "render_overlay": "overlay",
    "replay": "rollout",
    "replay_episode": "eval_rollouts",
    "short_cut": "cuts",
    "write_page": "review",
}
"""Public name -> submodule; imported on first access so ``python -m`` runs of a
submodule do not import it twice."""

__all__ = [
    "EvalRun",
    "HeuristicPolicy",
    "NetworkPolicy",
    "Policy",
    "RandomPolicy",
    "Rollout",
    "build_assets",
    "evaluate",
    "evaluate_spec",
    "game_for",
    "gif",
    "load_eval",
    "long_cut",
    "network_outputs",
    "play",
    "render_kept",
    "render_master",
    "render_overlay",
    "replay",
    "replay_episode",
    "short_cut",
    "write_page",
]


def __getattr__(name: str) -> object:
    """Import a public name from its submodule on first access."""
    module = _EXPORTS.get(name)
    if module is None:
        msg = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(msg)
    return getattr(importlib.import_module(f".{module}", __name__), name)
