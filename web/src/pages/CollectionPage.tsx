// The landing view: is the news-drift collection still running, and will the
// rows it is banking count?
//
// THIS PAGE CANNOT SHOW AN OUTCOME, and that is its defining constraint. The
// holdout is evaluated ONCE, at stage 4, against pre-registered tests. A panel
// charting excess return would turn a once-only evaluation into a daily glance,
// and every decision the pre-registration exists to constrain (stop early,
// extend, restrict the band) would then be made by someone who already knew the
// answer. Seven amendments went into protecting that ordering.
//
// The backend refuses to send an outcome (api_server/collection.py raises), so
// this component has nothing to filter. It renders counts, floors, states and
// timestamps. If you are about to add a return, benchmark, excess or net field
// here, the answer is no.
import { useApi } from "../api/useApi";
import { api } from "../api/client";
import type { CollectionMonitor } from "../api/types";
import { DataState, Panel } from "../components/ui";

function Bar({ value, target, label }: {
  value: number; target: number; label: string;
}) {
  const pct = target > 0 ? Math.min(100, (value / target) * 100) : 0;
  const done = value >= target;
  return (
    <div style={{ marginBottom: 12 }}>
      <div className="flex" style={{ justifyContent: "space-between" }}>
        <span>{label}</span>
        <span className="mono">
          <b className={done ? "pos" : ""}>{value}</b>
          <span className="dim"> / {target}</span>
        </span>
      </div>
      <div style={{ height: 6, background: "var(--line, #222)", borderRadius: 3,
                    marginTop: 5, overflow: "hidden" }}>
        <div style={{ width: `${pct}%`, height: "100%",
                      background: done ? "var(--pos, #3fb950)"
                                       : "var(--accent, #c9a227)" }} />
      </div>
    </div>
  );
}

function Counts({ data }: { data: Record<string, number> }) {
  const rows = Object.entries(data);
  if (rows.length === 0) return <div className="dim">none</div>;
  return (
    <>
      {rows.map(([k, v]) => (
        <div className="kv" key={k}>
          <span className="mono">{k}</span><span className="mono">{v}</span>
        </div>
      ))}
    </>
  );
}

export default function CollectionPage() {
  // 30 seconds. The underlying job runs once a weekday, so a faster poll would
  // add load without adding information.
  const m = useApi<CollectionMonitor>(() => api.collectionMonitor(), 30000, []);
  const d = m.data;

  return (
    <div>
      <h1 className="page-title">Collection</h1>
      <p className="page-sub">
        News-drift experiment, stage 3. This view reports progress and
        scheduler health. It does not and cannot report an outcome: the holdout
        is evaluated once, at stage 4, against the pre-registered tests.
      </p>

      <DataState loading={m.loading && !d} error={m.error}>
        {d && (
          <div>
            {/* Alarms first. A missed session is unrecoverable, so anything
                saying collection stopped belongs above everything else. */}
            {d.alarms.length > 0 ? (
              <div style={{ marginBottom: 16 }} data-testid="alarms">
                {d.alarms.map((a, i) => (
                  <div key={i}
                       className={`callout ${a.level === "critical" ? "warn" : ""}`}
                       data-testid={`alarm-${a.code}`}
                       style={{ marginBottom: 8 }}>
                    <b>{a.level === "critical" ? "CRITICAL" : "WARNING"}</b>
                    {" · "}<span className="mono">{a.code}</span>
                    <div>{a.message}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="callout" data-testid="alarms-clear"
                   style={{ marginBottom: 16 }}>
                No alarms. The scheduler is armed, no session has been missed,
                and nothing says the sample is degrading.
              </div>
            )}

            <div className="grid">
              <Panel title="Progress">
                {d.progress ? (
                  <>
                    <Bar label="Day clusters (floor)"
                         value={d.progress.day_clusters}
                         target={d.progress.cluster_floor} />
                    <Bar label="Judged observations"
                         value={d.progress.judged}
                         target={d.progress.judged_target} />
                    <div className="kv">
                      <span>hard stop</span>
                      <span className="mono">
                        {d.progress.day_clusters} / {d.progress.hard_stop}
                        <span className="dim">
                          {" "}({d.progress.clusters_to_hard_stop} left)
                        </span>
                      </span>
                    </div>
                    <div className="kv">
                      <span>scored directional</span>
                      <span className="mono">
                        {d.progress.scored_directional}</span>
                    </div>
                    <div className="kv">
                      <span>sessions collected</span>
                      <span className="mono">
                        {d.progress.first_session ?? "—"}
                        {" .. "}{d.progress.last_session ?? "—"}</span>
                    </div>
                    <div className="ctrl-sub" style={{ marginTop: 8 }}>
                      {d.progress.clusters_to_floor > 0
                        ? `${d.progress.clusters_to_floor} more trading sessions before the registered cluster floor is met. Each one missed is unrecoverable.`
                        : "The cluster floor is met."}
                    </div>
                  </>
                ) : <div className="dim">no data</div>}
              </Panel>

              <Panel title="Per stratum (E-test floors)">
                {d.progress && d.progress.per_stratum.length > 0 ? (
                  d.progress.per_stratum.map((s) => (
                    <div key={s.stratum} data-testid={`stratum-${s.stratum}`}>
                      <Bar label={`${s.stratum} clusters`}
                           value={s.day_clusters} target={s.cluster_floor} />
                      <div className="ctrl-sub" style={{ marginTop: -6,
                                                         marginBottom: 10 }}>
                        {s.judged} judged
                        {!s.meets_floor && " · below the 30-cluster floor, so this stratum's E-test would abstain"}
                      </div>
                    </div>
                  ))
                ) : <div className="dim">no strata yet</div>}
              </Panel>

              <Panel title="Scheduler">
                <div className="kv"><span>timer</span>
                  <span className={`mono ${d.run_health.timer.timer_active ? "pos" : "neg"}`}>
                    {!d.run_health.timer.known ? "UNKNOWN"
                      : d.run_health.timer.timer_active ? "active" : "INACTIVE"}
                  </span></div>
                <div className="kv"><span>service failed</span>
                  <span className={`mono ${d.run_health.timer.unit_failed ? "neg" : "pos"}`}>
                    {d.run_health.timer.unit_failed === null ? "unknown"
                      : d.run_health.timer.unit_failed ? "FAILED" : "no"}
                  </span></div>
                <div className="kv"><span>next fire</span>
                  <span className="mono">
                    {d.run_health.timer.next_fire_utc ?? "—"}</span></div>
                <div className="kv"><span>sessions behind</span>
                  <span className="mono">
                    {d.run_health.calendar.sessions_behind ?? "—"}</span></div>
                <div className="kv"><span>next expected session</span>
                  <span className="mono">
                    {d.run_health.calendar.next_expected ?? "—"}</span></div>
                <div className="kv"><span>gaps (permanent)</span>
                  <span className={`mono ${d.run_health.gap_count ? "neg" : "pos"}`}
                        data-testid="gap-summary">
                    {d.run_health.gap_count === 0 ? "none"
                      : d.run_health.gaps.join(", ")}</span></div>
                {d.run_health.timer.error && (
                  <div className="ctrl-sub">{d.run_health.timer.error}</div>
                )}
              </Panel>

              <Panel title="Last run">
                {d.run_health.last_run ? (
                  <>
                    <div className="kv"><span>started</span>
                      <span className="mono">
                        {d.run_health.last_run.started_utc}</span></div>
                    <div className="kv"><span>target session</span>
                      <span className="mono">
                        {d.run_health.last_run.target ?? "—"}</span></div>
                    <div className="kv"><span>formation</span>
                      <span className="mono">
                        {d.run_health.last_run.formation ?? "—"}</span></div>
                    <div className="kv"><span>action</span>
                      <span className="mono">
                        {d.run_health.last_run.action ?? "—"}</span></div>
                    <div className="kv"><span>exit</span>
                      <span className={`mono ${d.run_health.last_run.exit_code ? "neg" : "pos"}`}>
                        {d.run_health.last_run.exit_code ?? "—"}</span></div>
                    {d.run_health.last_run.detail && (
                      <div className="ctrl-sub" style={{ marginTop: 6 }}>
                        {d.run_health.last_run.detail}</div>
                    )}
                    <div className="ctrl-sub" style={{ marginTop: 6 }}>
                      {d.run_health.runs_recorded} runs recorded in
                      COLLECTION_LOG.md
                    </div>
                  </>
                ) : <div className="dim">no run recorded</div>}
              </Panel>

              <Panel title="Sample composition">
                {d.composition ? (
                  <>
                    <Counts data={d.composition.states} />
                    <div className="group-label" style={{ marginTop: 12 }}>
                      excluded_pre_call by error class
                    </div>
                    <div className="ctrl-sub">
                      Sample composition. A rising rate means the effective
                      sample is smaller than the row count.
                    </div>
                    <Counts data={d.composition.excluded_pre_call_by_error_class} />
                    <div className="group-label" style={{ marginTop: 12 }}>
                      model_failed by error class
                    </div>
                    <div className="ctrl-sub">
                      Operational health. A rising rate means go and look at the
                      provider. Never summed with the above.
                    </div>
                    <Counts data={d.composition.model_failed_by_error_class} />
                    <div className="kv" style={{ marginTop: 12 }}>
                      <span>source_failed share</span>
                      <span className="mono">
                        {(d.composition.source_failed_fraction * 100).toFixed(1)}%
                      </span></div>
                    <div className="group-label" style={{ marginTop: 12 }}>
                      rows that cannot count
                    </div>
                    <Counts data={d.composition.non_collection_rows} />
                  </>
                ) : <div className="dim">no data</div>}
              </Panel>

              <Panel title="Judgment balance (pre-registered diagnostic)">
                {d.judgment ? (
                  <>
                    <div className="kv"><span>POSITIVE</span>
                      <span className="mono">{d.judgment.positive}</span></div>
                    <div className="kv"><span>NEGATIVE</span>
                      <span className="mono">{d.judgment.negative}</span></div>
                    <div className="kv"><span>NEUTRAL</span>
                      <span className="mono">{d.judgment.neutral}</span></div>
                    <div className="kv"><span>minority share</span>
                      <span className={`mono ${d.judgment.minority_share >= d.judgment.minority_share_floor ? "pos" : "neg"}`}
                            data-testid="minority-share">
                        {(d.judgment.minority_share * 100).toFixed(1)}%
                        <span className="dim">
                          {" "}floor {(d.judgment.minority_share_floor * 100).toFixed(0)}%
                        </span>
                      </span></div>
                    <div className="kv"><span>NEUTRAL rate</span>
                      <span className="mono">
                        {(d.judgment.neutral_rate * 100).toFixed(1)}%
                        <span className="dim">
                          {" "}bar {(d.judgment.neutral_reportable_failure_bar * 100).toFixed(0)}%
                        </span>
                      </span></div>
                    <div className="kv"><span>mixed day clusters</span>
                      <span className="mono">
                        {d.judgment.mixed_day_clusters}
                        <span className="dim">
                          {" "}/ {d.judgment.mixed_cluster_floor}</span>
                      </span></div>
                    <div className="ctrl-sub" style={{ marginTop: 8 }}>
                      The permutation null needs both the minority share and the
                      mixed-cluster count above their floors. Below either, every
                      affected primary reads as an abstention rather than a
                      result. This is a diagnostic about the model's own
                      answers, not an outcome.
                    </div>
                  </>
                ) : <div className="dim">no data</div>}
              </Panel>

              <Panel title="Strength (pre-registered diagnostic)">
                {d.strength ? (
                  <>
                    <Counts data={d.strength.histogram} />
                    <div className="kv" style={{ marginTop: 10 }}>
                      <span>distinct values</span>
                      <span className="mono">
                        {d.strength.distinct_values}</span></div>
                    <div className="kv"><span>degenerate</span>
                      <span className={`mono ${d.strength.degenerate ? "neg" : "pos"}`}>
                        {d.strength.degenerate ? "YES" : "no"}</span></div>
                    <div className="kv"><span>unparseable</span>
                      <span className="mono">
                        {d.strength.unparseable}</span></div>
                    <div className="ctrl-sub" style={{ marginTop: 8 }}>
                      A degenerate distribution makes both strength secondaries
                      uninformative. NEUTRAL is excluded here because its
                      strength is fixed at 1 by the prompt.
                    </div>
                  </>
                ) : <div className="dim">no data</div>}
              </Panel>

              <Panel title="Spend">
                {d.spend ? (
                  <>
                    <div className="kv"><span>total</span>
                      <span className="mono">
                        {d.spend.total_usd.toFixed(6)} USD</span></div>
                    <div className="kv"><span>calls</span>
                      <span className="mono">{d.spend.calls}</span></div>
                    <div className="kv"><span>per call</span>
                      <span className="mono">
                        {d.spend.per_call?.toFixed(8) ?? "—"}
                        <span className="dim">
                          {" "}measured {d.spend.measured_per_call}</span>
                      </span></div>
                    <div className="kv"><span>drift</span>
                      <span className="mono">
                        {d.spend.per_call_drift_pct === null ? "—"
                          : `${d.spend.per_call_drift_pct > 0 ? "+" : ""}${d.spend.per_call_drift_pct}%`}
                      </span></div>
                    <div className="group-label" style={{ marginTop: 12 }}>
                      per session
                    </div>
                    {d.spend.per_session.map((s) => (
                      <div className="kv" key={s.session}>
                        <span className="mono">{s.session}</span>
                        <span className="mono">
                          {s.usd.toFixed(6)} USD
                          <span className="dim"> · {s.calls} calls</span>
                        </span>
                      </div>
                    ))}
                  </>
                ) : <div className="dim">no data</div>}
              </Panel>
            </div>

            <div className="ctrl-sub" style={{ marginTop: 16 }}
                 data-testid="exclusion-note">
              {d.exclusion_note} Excluded by construction:{" "}
              <span className="mono">
                {d.outcome_columns_excluded.join(", ")}</span>.
            </div>
            <div className="ctrl-sub">generated {d.generated_utc}</div>
          </div>
        )}
      </DataState>
    </div>
  );
}
