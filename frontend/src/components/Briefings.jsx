import {
  useEffect,
  useState,
} from "react";

import InventoryEvidence from "./InventoryEvidence.jsx";
import {
  Empty,
  EvidenceCard,
  RiskBadge,
  StatusChip,
  precisePct,
} from "./ui.jsx";


function evidenceText(
  structuredEvidence,
) {
  if (!structuredEvidence) {
    return [];
  }

  return [
    [
      "Shipment",
      structuredEvidence.shipmentSummary,
    ],

    [
      "Historical delay",
      structuredEvidence
        .historicalDelaySummary,
    ],

    [
      "Destination weather",
      structuredEvidence.weatherSummary,
    ],

    [
      "Alternative supplier",
      structuredEvidence.supplierStatus,
    ],

    [
      "Inventory",
      structuredEvidence
        .inventorySummary
      || (
        structuredEvidence
          .inventoryCoverageDays
        !== null
        && structuredEvidence
          .inventoryCoverageDays
        !== undefined
          ? (
            `${structuredEvidence
              .inventoryCoverageDays} days coverage`
          )
          : (
            "Not available. Stockout exposure "
            + "cannot be confirmed."
          )
      ),
    ],
  ].filter(
    (
      [
        ,
        value,
      ],
    ) =>
      value !== null
      && value !== undefined
      && value !== "",
  );
}


function buildClipboardText(
  shipment,
) {
  const briefing = (
    shipment.briefing
  );

  const evidence = evidenceText(
    shipment.structuredEvidence,
  );

  const actions = (
    briefing.recommendedActions
    || shipment.recommendedActions
    || []
  );

  const citations = (
    briefing.citations
    || shipment.ragPolicyCitations
    || []
  );

  const retrieval = (
    briefing.retrieval
    || shipment.retrieval
    || null
  );

  const limitations = (
    briefing.limitations
    || shipment.limitations
    || []
  );

  const lines = [
    "DISRUPTION BRIEFING",
    "",
    `Shipment: ${shipment.id}`,
    `Risk: ${String(
      shipment.riskLevel,
    ).toUpperCase()}`,
    (
      "Delay probability: "
      + precisePct(
        shipment.delayProbability,
      )
    ),
    "",
    "EXECUTIVE SUMMARY",
    briefing.summary,
  ];

  if (evidence.length) {
    lines.push(
      "",
      "COLLECTED EVIDENCE",
    );

    for (
      const [
        label,
        value,
      ]
      of evidence
    ) {
      lines.push(
        `${label}: ${value}`,
      );
    }
  }

  if (actions.length) {
    lines.push(
      "",
      "RECOMMENDED ACTIONS",
    );

    actions.forEach(
      (
        action,
        index,
      ) => {
        lines.push(
          `${index + 1}. ${action}`,
        );
      },
    );
  }

  if (citations.length) {
    lines.push(
      "",
      "OPERATIONAL GUIDANCE USED",
    );

    citations.forEach(
      (
        citation,
      ) => {
        lines.push(
          `- ${citation}`,
        );
      },
    );
  } else {
    lines.push(
      "",
      "SUPPORTING DOCUMENTS",
      (
        "- None. "
        + (
          retrieval?.message
          || (
            "This briefing cites no operational "
            + "procedures."
          )
        )
      ),
    );
  }

  if (limitations.length) {
    lines.push(
      "",
      "LIMITATIONS",
    );

    limitations.forEach(
      (
        limitation,
      ) => {
        lines.push(
          `- ${limitation}`,
        );
      },
    );
  }

  lines.push(
    "",
    (
      "Generated: "
      + briefing.generatedAt
    ),
  );

  return lines.join("\n");
}

function HistoricalDelayEvidence({
  summary,
}) {
  if (!summary) {
    return (
      <p className="muted-text">
        Historical-delay evidence was not available.
      </p>
    );
  }

  const marker = "Highest factor:";
  const markerIndex = summary.indexOf(marker);

  if (markerIndex === -1) {
    return <p>{summary}</p>;
  }

  const rates = summary
    .slice(0, markerIndex)
    .trim();

  const highestFactor = summary
    .slice(markerIndex + marker.length)
    .trim();

  return (
    <>
      <p>{rates}</p>

      <div className="highest-factor">
        <span>
          Highest factor
        </span>

        <strong>
          {highestFactor}
        </strong>
      </div>
    </>
  );
}

function EvidenceSection({
  shipment,
}) {
  const evidence = (
    shipment.structuredEvidence
  );

  if (!evidence) {
    return null;
  }

  const inventoryCoverage = (
    evidence.inventoryCoverageDays
  );
  const inventoryRecord = (
    evidence.inventoryRecord
  );

  return (
    <section className="briefing-section">
      <div className="section-copy">
        <small className="eyebrow">
          Grounding
        </small>

        <h3>
          Evidence used in the briefing
        </h3>

        <p>
          These findings were collected by the backend
          tools before the briefing was generated.
        </p>
      </div>

      <div className="evidence-grid">
        <EvidenceCard title="Historical delay">
          <HistoricalDelayEvidence
            summary={
              evidence
                .historicalDelaySummary
            }
          />
        </EvidenceCard>

        <EvidenceCard title="Destination weather">
          {evidence.weatherSummary
            ? (
              <p>
                {
                  evidence.weatherSummary
                }
              </p>
            )
            : (
              <p className="muted-text">
                Destination-weather evidence was not
                available.
              </p>
            )}
        </EvidenceCard>

        <EvidenceCard
          title="Alternative supplier"
          tone="synthetic"
        >
          {evidence.supplierStatus
            ? (
              <>
                <p>
                  {
                    evidence
                      .supplierStatus
                  }
                </p>

                <p className="disclosure">
                  Human
                  validation is required before changing
                  suppliers.
                </p>
              </>
            )
            : (
              <p className="muted-text">
                Supplier evidence was not available.
              </p>
            )}
        </EvidenceCard>

        <EvidenceCard
          title="Product inventory record"
          tone="synthetic"
        >
          <InventoryEvidence
            record={inventoryRecord}
            summary={
              evidence.inventorySummary
            }
            coverage={inventoryCoverage}
            compact
          />
        </EvidenceCard>
      </div>
    </section>
  );
}


function RecommendedActions({
  actions,
}) {
  if (!actions.length) {
    return (
      <p className="muted-text">
        No grounded recommendations were generated.
      </p>
    );
  }

  return (
    <ol className="briefing-actions">
      {actions.map(
        (
          action,
          index,
        ) => (
          <li
            key={
              `${index}-${action}`
            }
          >
            <span className="briefing-action-number">
              {index + 1}
            </span>

            <p>
              {action}
            </p>
          </li>
        ),
      )}
    </ol>
  );
}


function OperationalGuidance({
  citations,
  retrieval,
}) {
  if (!citations.length) {
    // Nothing was retrieved, so nothing is listed as a source.
    return (
      <div
        className="inventory-alert"
        role="status"
      >
        <strong>
          {
            retrieval?.title
            || "No supporting documents retrieved"
          }
        </strong>
        <p>
          {
            retrieval?.message
            || (
              "This briefing cites no operational "
              + "procedures. It is based only on the "
              + "evidence collected by the investigation."
            )
          }
        </p>
      </div>
    );
  }

  return (
    <div className="citation-list">
      {citations.map(
        (
          citation,
        ) => (
          <article
            className="citation-card"
            key={
              citation.filename
              || citation.title
            }
          >
            <span className="citation-type">
              {
                citation.sourceType
                || (
                  "Operational "
                  + "guidance"
                )
              }
            </span>

            <strong>
              {citation.title}
            </strong>

            <small>
              {citation.filename}
            </small>
          </article>
        ),
      )}
    </div>
  );
}


export default function Briefings({
  shipment,
}) {
  const [
    copied,
    setCopied,
  ] = useState(false);

  const [
    copyError,
    setCopyError,
  ] = useState(false);

  useEffect(
    () => {
      setCopied(false);
      setCopyError(false);
    },
    [
      shipment?.id,
      shipment?.briefing,
    ],
  );

  if (!shipment) {
    return (
      <Empty>
        Select a shipment first.
      </Empty>
    );
  }

  const briefing = (
    shipment.briefing
  );

  if (!briefing) {
    if (
      shipment.investigationStatus
        === "running"
      || shipment.investigationStatus
        === "generating_briefing"
    ) {
      return (
        <Empty>
          The disruption briefing is being generated.
        </Empty>
      );
    }

    if (
      shipment.investigationStatus
        === "not_required"
    ) {
      return (
        <Empty>
          This shipment is low risk and does not require a
          disruption briefing.
        </Empty>
      );
    }

    return (
      <Empty>
        No briefing yet. Run an investigation for this
        shipment first.
      </Empty>
    );
  }

  const actions = (
    briefing.recommendedActions
    || shipment.recommendedActions
    || []
  );

  const citationCards = (
    briefing.citationCards
    || shipment.citationCards
    || []
  );

  const retrieval = (
    briefing.retrieval
    || shipment.retrieval
    || null
  );

  const limitations = (
    briefing.limitations
    || shipment.limitations
    || []
  );

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(
        buildClipboardText(
          shipment,
        ),
      );

      setCopied(true);
      setCopyError(false);

      window.setTimeout(
        () => {
          setCopied(false);
        },
        1500,
      );
    } catch {
      setCopyError(true);
      setCopied(false);
    }
  };

  return (
    <div className="briefing-layout">
      <section className="panel brief">
        <header className="briefing-header">
          <div>
            <small className="eyebrow">
              Azure-grounded decision support
            </small>

            <h2>
              Disruption briefing
            </h2>

            <p>
              Evidence-grounded assessment for
              {" "}
              <strong>
                {shipment.id}
              </strong>
              .
            </p>
          </div>

          <div className="briefing-controls">
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

            <button
              className="btn"
              onClick={copy}
            >
              {copied
                ? "Copied"
                : "Copy briefing"}
            </button>
          </div>
        </header>

        {copyError && (
          <p className="copy-error">
            The briefing could not be copied. Please
            select and copy the text manually.
          </p>
        )}

        <div className="briefing-risk">
          <div>
            <span>Shipment</span>

            <strong>
              {shipment.id}
            </strong>
          </div>

          <div>
            <span>Risk level</span>

            <strong>
              {String(
                shipment.riskLevel,
              ).toUpperCase()}
            </strong>
          </div>

          <div>
            <span>Delay probability</span>

            <strong>
              {precisePct(
                shipment.delayProbability,
              )}
            </strong>
          </div>
        </div>

        <section className="executive-summary">
          <small className="eyebrow">
            Executive summary
          </small>

          <p className="lead">
            {briefing.summary}
          </p>
        </section>
      </section>

      <EvidenceSection
        shipment={shipment}
      />

      <section className="panel briefing-section">
        <div className="section-copy">
          <small className="eyebrow">
            Decision support
          </small>

          <h3>
            Recommended actions
          </h3>

          <p>
            Recommendations are advisory and require
            operational review before execution.
          </p>
        </div>

        <RecommendedActions
          actions={actions}
        />
      </section>

      <section className="panel briefing-section">
        <div className="section-copy">
          <small className="eyebrow">
            RAG knowledge
          </small>

          <h3>
            {citationCards.length > 0
              ? "Operational policies used"
              : "Supporting documents"}
          </h3>
          {citationCards.length > 0 && (
            <p>
              These documents were retrieved from
              the operational knowledge base and supplied as
              grounding context.
            </p>
          )}
        </div>

        <OperationalGuidance
          citations={citationCards}
          retrieval={retrieval}
        />
      </section>

      {limitations.length > 0 && (
        <section className="panel briefing-section limitations-panel">
          <div className="section-copy">
            <small className="eyebrow">
              Transparency
            </small>

            <h3>
              Limitations
            </h3>

            <p>
              These constraints define what the briefing
              can and cannot support.
            </p>
          </div>

          <ul className="limitations-list">
            {limitations.map(
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

      <footer className="briefing-footer">
        <span>
          Generated {briefing.generatedAt}
        </span>

        <span>
          Human validation required before operational use.
        </span>
      </footer>
    </div>
  );
}