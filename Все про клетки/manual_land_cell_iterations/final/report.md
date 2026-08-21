# Manual land-cell iteration report
Task: 50 sequential manual iterations for land-cell generation on four fixed test territories: La Coruña (4 cells), Greater London (5), Brittany (6), Sicily (6).
Fixed city points used: La Coruña, London, Rennes, Palermo.
Core working files:
- `manual_land_cell_iterations/generator/manual_land_cell_generator.py`
- `manual_land_cell_iterations/fixed_test_geometry/*.json`
- `manual_land_cell_iterations/output/iteration_###/`

## Iteration progression (score + new-best flag)
| Iter | Score | New best | Short note |
|---:|---:|:---:|---|
| 001 | 0.000 | yes |  |
| 002 | 0.000 | yes | Raised noise and grid resolution to make boundaries less rectilinear. |
| 003 | 0.000 | no | Tested stronger noise plus one round of post-smoothing. |
| 004 | 6.005 | no | Changed seed and slightly altered noise / city protection. |
| 005 | 0.000 | no | Re-tested 002-like parameters with experimental rotated split candidates. |
| 006 | 0.000 | no | Lowered neck strength and city protection to see if large sectors relaxed. |
| 007 | 7.240 | no | Re-ran the 002 configuration after scoring and generator cleanup. |
| 008 | 7.240 | no | Reduced city protection ratio; output remained effectively unchanged. |
| 009 | 22.104 | yes | Tried a different deterministic seed around the 007/002 profile. |
| 010 | 6.876 | no | Another seed variant around the same profile. |
| 011 | 22.936 | yes | Seed variant with slightly smoother global balance. |
| 012 | 8.714 | no | Seed sweep continue. |
| 013 | 11.617 | no | Seed sweep continue. |
| 014 | 0.000 | no | Seed sweep continue; technical quality slipped slightly. |
| 015 | 3.065 | no | Seed sweep continue. |
| 016 | 13.435 | no | Seed sweep continue. |
| 017 | 24.806 | yes | Best seed from the sweep: lower parallelism and fewer long straight sections. |
| 018 | 13.038 | no | Last seed in the sweep. |
| 019 | 24.399 | no | Reduced noise strength. |
| 020 | 9.632 | no | Raised noise strength moderately. |
| 021 | 14.927 | no | Raised noise strength further. |
| 022 | 16.448 | no | Lower noise scale ratio. |
| 023 | 22.230 | no | Higher noise scale ratio. |
| 024 | 0.000 | no | Very high noise scale ratio. |
| 025 | 15.205 | no | Lower final simplify tolerance. |
| 026 | 20.253 | no | Higher final simplify tolerance. |
| 027 | 24.771 | no | Very high final simplify tolerance. |
| 028 | 0.000 | no | Lower grid resolution. |
| 029 | 0.000 | no | Higher grid resolution. |
| 030 | 0.000 | no | Very high grid resolution. |
| 031 | 14.785 | no | Lower neck strength. |
| 032 | 10.913 | no | Higher neck strength. |
| 033 | 23.686 | no | Very low neck strength. |
| 034 | 22.104 | no | Higher minimum component ratio. |
| 035 | 22.104 | no | Higher minimum neck lobe ratio. |
| 036 | 22.104 | no | Lower allowed area ratio threshold. |
| 037 | 13.181 | no | Lower city protection ratio. |
| 038 | 31.608 | yes | Higher city protection ratio (final winner). |
| 039 | 11.505 | no | Very high city protection ratio. |
| 040 | 22.104 | no | Lower opponent seed count. |
| 041 | 0.000 | no | Combined lower noise strength + lower noise scale with seed 20260713. |
| 042 | 22.461 | no | Combined higher noise strength + slightly higher noise scale with seed 20260713. |
| 043 | 0.571 | no | Combined lower city protection with tuned noise and seed 20260713. |
| 044 | 15.269 | no | Combined larger grid with tuned noise and seed 20260713. |
| 045 | 8.792 | no | Combined lower noise settings with seed 20260718. |
| 046 | 15.697 | no | Combined slightly stronger noise with seed 20260718. |
| 047 | 0.000 | no | Combined lower city protection + larger grid with seed 20260719. |
| 048 | 4.174 | no | Combined stronger noise + higher simplify with seed 20260721. |
| 049 | 0.000 | no | Combined lower noise scale + lower city protection with seed 20260722. |
| 050 | 0.000 | no | Combined lower noise strength + lower grid with seed 20260723. |

## Best result
- Chosen best iteration: **038**
- Main reason: among all outputs, iteration 038 had the best overall visual compromise across all four territories: low parallel-penalty score, good area balance, no coverage/connectivity failures, smooth but not over-straight internal lines, and especially a cleaner London + Sicily while keeping Brittany acceptable.
- Score snapshot: see `final/best_metrics.json`.

## Important qualitative findings
1. Moderate noise with moderate simplify was consistently better than both very low-noise straight cuts and high-noise jagged cuts.
2. Random seed mattered a lot. Several of the strongest iterations were simple seed variations around the same parameter family.
3. Raising city protection a little (iteration 038) improved balance around the city cell without collapsing the outer cells.
4. Experimental rotated split-candidate override was not kept; it did not outperform the base split strategy on the fixed test set.
5. Heavy post-smoothing also did not help; it tended to wash out useful irregularity.

## Deliverables
- Final best overview: `manual_land_cell_iterations/final/best_overview.png`
- Final best single renders: `best_la_coruna.png`, `best_london.png`, `best_brittany.png`, `best_sicily.png`
- Best metadata: `best_params.json`, `best_metrics.json`, `best_notes.json`, `best_cells.json`
