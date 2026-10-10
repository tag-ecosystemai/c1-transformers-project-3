import {
  Empty,
  RiskBadge,
  StatusChip,
} from "./ui.jsx";


function DecisionNotice({
  decision,
}) {
  if (!decision) {
    return null;
  }

  return (
    <p
      className={
        `decision-notice ${decision}`
      }
    >
      {decision === "approved"
        ? (
          "Marked for operational review. "
          + "No backend action has been executed."
        )
        : (
          "Dismissed in this browser session. "
          + "No backend record has been changed."
        )}
    </p>
  );
}


export default function Actions({
  shipment,
  decisions,
  onDecide,
  onViewBriefing,
}) {
  if (!shipment) {
    return (
      <Empty>
        Select a shipment first.
      </Empty>
    );
  }

  const recommendations = (
    shipment.recommendations
    || []
  );

  if (!recommendations.length) {
    const status = (
      shipment.investigationStatus
    );

    if (
      status === "running"
      || status === "generating_briefing"
    ) {
      return (
        <Empty>
          Recommendations will appear when the
          investigation and grounded briefing are complete.
        </Empty>
      );
    }

    if (status === "not_required") {
      return (
        <Empty>
          This shipment is low risk and does not require a
          full disruption investigation.
        </Empty>
      );
    }

    return (
      <Empty>
        No recommendations yet. Run an investigation for
        this shipment first.
      </Empty>
    );
  }

  const shown = (
    value,
  ) => (
    value
    ?? "Not assessed"
  );

  return (
    <div className="actions-layout">
      <section className="panel">
        <header className="actions-header">
          <div>
            <small className="eyebrow">
              Decision support
            </small>

            <h2>
              Recommended actions
            </h2>

            <p>
              {shipment.citationCards?.length > 0
                ? (
                  `Grounded recommendations for ${shipment.id}, `
                  + "generated from the collected evidence and "
                  + "retrieved synthetic operational guidance."
                )
                : (
                  `Recommendations for ${shipment.id}, generated `
                  + "from the collected evidence only. No "
                  + "supporting documents were retrieved."
                )}
            </p>
          </div>

          <div className="header-actions">
            <RiskBadge
              level={
                shipment.riskLevel
              }
            />

            <StatusChip
              status={
                shipment.investigationStatus
              }
            />
          </div>
        </header>

        <div className="decision-disclosure">
          <strong>
            Human approval is required
          </strong>

          <p>
            Mark for review and Dismiss are local controls
            for this demonstration. These controls do not
            reroute a shipment, change a supplier, reserve
            inventory, or update the backend.
          </p>
        </div>
      </section>

      <section className="cards action-cards">
        {recommendations.map(
          (
            recommendation,
            index,
          ) => {
            const decision = (
              decisions[
                recommendation.id
              ]
            );

            return (
              <article
                key={
                  recommendation.id
                }
                className={
                  (
                    "card action-card "
                    + (
                      decision
                      || ""
                    )
                  )
                }
              >
                <div className="action-number">
                  {index + 1}
                </div>

                <div className="action-card-content">
                  <span className="action-source">
                    {
                      recommendation.source
                      || (
                        "Grounded disruption "
                        + "briefing"
                      )
                    }
                  </span>

                  <h3>
                    {recommendation.title}
                  </h3>

                  {recommendation.detail && (
                    <p className="action-detail">
                      {
                        recommendation.detail
                      }
                    </p>
                  )}

                  <dl className="trade">
                    <div>
                      <dt>Cost</dt>

                      <dd>
                        {shown(
                          recommendation.cost,
                        )}
                      </dd>
                    </div>

                    <div>
                      <dt>Time</dt>

                      <dd>
                        {shown(
                          recommendation.time,
                        )}
                      </dd>
                    </div>

                    <div>
                      <dt>Residual risk</dt>

                      <dd>
                        {shown(
                          recommendation.risk,
                        )}
                      </dd>
                    </div>
                  </dl>

                  <DecisionNotice
                    decision={decision}
                  />

                  {!decision && (
                    <div className="btns">
                      <button
                        className="btn"
                        onClick={() =>
                          onDecide(
                            recommendation.id,
                            "approved",
                          )
                        }
                      >
                        Mark for review
                      </button>

                      <button
                        className="btn ghost"
                        onClick={() =>
                          onDecide(
                            recommendation.id,
                            "dismissed",
                          )
                        }
                      >
                        Dismiss
                      </button>
                    </div>
                  )}
                </div>
              </article>
            );
          },
        )}
      </section>

      {shipment.limitations?.length > 0 && (
        <section className="panel limitations-panel">
          <div className="section-copy">
            <small className="eyebrow">
              Before taking action
            </small>

            <h3>
              Operational constraints
            </h3>

            <p>
              Review these limitations before accepting
              any recommendation.
            </p>
          </div>

          <ul className="limitations-list">
            {shipment.limitations.map(
              (
                limitation,
                index,
              ) => (
                <li
                  key={
                    `${index}-${limitation}`
                  }
                >
                  {limitation}
                </li>
              ),
            )}
          </ul>
        </section>
      )}
      {shipment.briefing && (
        <nav
          className="page-navigation"
          aria-label="Continue to disruption briefing"
        >
          <div>
            <small className="eyebrow">
              Final step
            </small>

            <strong>
              Review the complete disruption briefing
            </strong>

            <p>
              Open the executive summary, collected evidence,
              recommended actions, policy citations, and
              limitations.
            </p>
          </div>

          <button
            type="button"
            className="btn page-navigation-button"
            onClick={onViewBriefing}
          >
            View disruption briefing
            <span aria-hidden="true">→</span>
          </button>
        </nav>
      )}
    </div>
  );
}