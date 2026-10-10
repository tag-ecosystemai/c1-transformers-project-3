import {
  Empty,
  Meter,
  NA,
  RiskBadge,
  StatusChip,
  money,
  pct,
  precisePct,
} from "./ui.jsx";


function Fact({
  label,
  value,
}) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>
        {value ?? NA}
      </dd>
    </div>
  );
}


function HistoricalDelayRates({
  shipment,
}) {
  const rates = (
    shipment.historicalDelayRates
    || {}
  );

  const factors = [
    {
      label:
        "Product",

      value:
        rates.product,
    },

    {
      label:
        "Market",

      value:
        rates.market,
    },

    {
      label:
        "Shipping mode",

      value:
        rates.shippingMode,
    },
  ];

  return (
    <section className="shipment-section">
      <div className="section-copy">
        <small className="eyebrow">
          Historical evidence
        </small>

        <h3>
          Recorded delay rates
        </h3>

        <p>
          Historical rates are context for investigation,
          not confirmation that this shipment will be
          delayed.
        </p>
      </div>

      <div className="stats small">
        {factors.map(
          (
            factor,
          ) => (
            <div
              className="stat"
              key={
                factor.label
              }
            >
              <b>
                {precisePct(
                  factor.value,
                )}
              </b>

              <span>
                {factor.label}
              </span>
            </div>
          ),
        )}
      </div>
    </section>
  );
}


function BusinessImpact({
  shipment,
}) {
  const impact = (
    shipment.impact
    || {}
  );

  const inventoryCoverage = (
    shipment.structuredEvidence
      ?.inventoryCoverageDays
  );
  const inventoryRecord = (
    shipment.structuredEvidence
      ?.inventoryRecord
  );

  return (
    <section className="shipment-section">
      <div className="section-copy">
        <small className="eyebrow">
          Business impact
        </small>

        <h3>
          Available impact information
        </h3>

        <p>
          The product's inventory record appears after an
          investigation retrieves it. It does not verify
          that stock is available for this shipment.
        </p>
      </div>

      <div className="stats small">
        <div className="stat">
          <b>
            {inventoryRecord
              ?.availableStock
              !== null
              && inventoryRecord
                ?.availableStock
                !== undefined
              ? (
                inventoryRecord
                  .availableStock
                  .toLocaleString()
              )
              : NA}
          </b>

          <span>
            Available units
          </span>
        </div>

        <div className="stat">
          <b>
            {inventoryCoverage !== null
              && inventoryCoverage !== undefined
              ? `${inventoryCoverage}d`
              : NA}
          </b>

          <span>
            Inventory coverage
          </span>
        </div>

        <div className="stat">
          <b>
            {inventoryRecord
              ?.stockoutRisk
              ? String(
                inventoryRecord
                  .stockoutRisk,
              ).toUpperCase()
              : NA}
          </b>

          <span>
            Stockout risk on record
          </span>
        </div>
      </div>
    </section>
  );
}


export default function Shipments({
  shipments,
  selectedId,
  onSelect,
}) {
  const shipment = (
    shipments.find(
      (
        item,
      ) =>
        item.id === selectedId,
    )
    || shipments[0]
  );

  if (!shipment) {
    return (
      <Empty>
        No shipments are available.
      </Empty>
    );
  }

  const details = (
    shipment.details
    || {}
  );

  const facts = [
    [
      "Product",
      details.product,
    ],

    [
      "Category",
      details.category,
    ],

    [
      "Department",
      details.department,
    ],

    [
      "Market",
      details.market,
    ],

    [
      "Destination",
      details.destination,
    ],

    [
      "Destination region",
      details.destinationRegion,
    ],

    [
      "Shipping mode",
      details.shippingMode
      || details.carrier,
    ],

    [
      "Scheduled shipping",
      details.scheduledDays
      !== null
      && details.scheduledDays
      !== undefined
        ? `${details.scheduledDays} days`
        : NA,
    ],

    [
      "Scheduled arrival",
      details.eta,
    ],

    [
      "Quantity",
      details.quantity,
    ],

    [
      "Sales value",
      money(
        details.sales,
      ),
    ],

    [
      "Operational status",
      details.status,
    ],
  ];

  return (
    <div className="split shipment-layout">
      <aside className="stack shipment-list">
        <div className="section-copy shipment-list-heading">
          <small className="eyebrow">
            Active shipments
          </small>

          <h2>
            Risk queue
          </h2>
        </div>

        {shipments.map(
          (
            item,
          ) => (
            <button
              key={
                item.id
              }
              className={
                (
                  "row compact "
                  + (
                    item.id
                      === shipment.id
                      ? "on"
                      : ""
                  )
                )
              }
              onClick={() =>
                onSelect(
                  item.id,
                )
              }
            >
              <strong>
                {item.id}
              </strong>

              <span>
                {
                  item.details
                    .destination
                }
              </span>

              <StatusChip
                status={
                  item
                    .investigationStatus
                }
              />

              <RiskBadge
                level={
                  item.riskLevel
                }
              />
            </button>
          ),
        )}
      </aside>

      <section className="panel shipment-detail">
        <header className="shipment-header">
          <div>
            <small className="eyebrow">
              Shipment assessment
            </small>

            <h2>
              {shipment.id}
            </h2>

            <p>
              Real shipment attributes and model prediction
              returned by the FastAPI backend.
            </p>
          </div>

          <div className="header-actions">
            <StatusChip
              status={
                shipment
                  .investigationStatus
              }
            />

            <RiskBadge
              level={
                shipment.riskLevel
              }
            />
          </div>
        </header>

        <div className="prob probability-card">
          <span>
            Delay probability
          </span>

          <Meter
            value={
              shipment
                .delayProbability
            }
            level={
              shipment.riskLevel
            }
          />

          <b>
            {precisePct(
              shipment.delayProbability,
            )}
          </b>
        </div>

        <div className="investigation-requirement">
          <strong>
            {shipment.requiresInvestigation
              ? (
                "AI investigation required"
              )
              : (
                "Routine monitoring"
              )}
          </strong>

          <p>
            {shipment.requiresInvestigation
              ? (
                "The predicted probability crossed the "
                + "investigation threshold."
              )
              : (
                "The shipment remains below the current "
                + "investigation threshold."
              )}
          </p>
        </div>

        <dl className="facts shipment-facts">
          {facts.map(
            (
              [
                label,
                value,
              ],
            ) => (
              <Fact
                key={label}
                label={label}
                value={value}
              />
            ),
          )}
        </dl>

        <HistoricalDelayRates
          shipment={shipment}
        />

        <BusinessImpact
          shipment={shipment}
        />

        {shipment.structuredEvidence
          ?.supplierStatus && (
          <section className="shipment-section">
            <div className="section-copy">
              <small className="eyebrow">
                Supplier evidence
              </small>

              <h3>
                Alternative supplier candidate
              </h3>
            </div>

            <div className="supplier-summary">
              <p>
                {
                  shipment
                    .structuredEvidence
                    .supplierStatus
                }
              </p>

              <small>
                Human validation is
                required before changing suppliers.
              </small>
            </div>
          </section>
        )}
      </section>
    </div>
  );
}