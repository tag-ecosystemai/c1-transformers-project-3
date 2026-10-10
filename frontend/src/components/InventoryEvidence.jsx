import {
  NA,
  RiskBadge,
  number,
} from "./ui.jsx";


const units = (
  value,
  suffix = "units",
) => (
  typeof value === "number"
  && Number.isFinite(value)
    ? `${value.toLocaleString()} ${suffix}`
    : NA
);


const NOT_VERIFIED = (
  "Stock availability for this shipment has not been verified."
);


/**
 * The inventory record held for the shipment's product.
 *
 * The record is product-level: it is matched on product name only and
 * does not show that stock is available for this shipment. The backend
 * sends no warehouse, supplier, reorder point, replenishment date or
 * destination match, so none is shown here.
 *
 * `record` holds the figures of the record, `summary` is the backend's
 * own description of it, and `coverage` is a whole-day figure used
 * only when neither is available.
 */
export default function InventoryEvidence({
  record,
  summary,
  coverage,
  compact = false,
}) {
  if (!record) {
    if (summary) {
      return (
        <p>
          {summary}
        </p>
      );
    }

    if (
      coverage !== null
      && coverage !== undefined
    ) {
      return (
        <>
          <strong className="evidence-value">
            {number(
              coverage,
              2,
            )} days
          </strong>
          <p>
            Inventory coverage was collected, but
            detailed stock evidence was not available.
          </p>
        </>
      );
    }

    return (
      <p className="muted-text">
        No inventory record is available. Stockout
        exposure cannot be confirmed.
      </p>
    );
  }

  const risk = String(
    record.stockoutRisk
    || "unknown",
  ).toLowerCase();

  return (
    <div
      className={
        `inventory-evidence ${compact ? "compact" : ""}`
      }
    >
      <div className="inventory-heading">
        <div>
          <strong>
            {record.productName}
          </strong>
          <span>
            Product-level record · stockout risk on record
          </span>
        </div>

        <RiskBadge
          level={risk}
        />
      </div>

      <dl className="inventory-facts">
        <div>
          <dt>Available stock</dt>
          <dd>
            {units(
              record.availableStock,
            )}
          </dd>
        </div>

        <div>
          <dt>Reserved stock</dt>
          <dd>
            {units(
              record.reservedStock,
            )}
          </dd>
        </div>

        <div>
          <dt>Daily demand</dt>
          <dd>
            {units(
              record.dailyDemand,
              "units/day",
            )}
          </dd>
        </div>

        <div>
          <dt>Coverage</dt>
          <dd>
            {number(
              record
                .inventoryCoverageDays,
              2,
            )} days
          </dd>
        </div>

        <div>
          <dt>Safety stock</dt>
          <dd>
            {units(
              record.safetyStock,
            )}
          </dd>
        </div>

        <div>
          <dt>Incoming inventory</dt>
          <dd>
            {units(
              record.incomingQuantity,
            )}
          </dd>
        </div>
      </dl>

      {record.belowSafetyStock && (
        <div
          className={
            `inventory-alert ${risk}`
          }
        >
          <p>
            Available stock is at or below safety stock.
          </p>
        </div>
      )}

      <p className="inventory-disclosure">
        {
          record.limitation
          || NOT_VERIFIED
        }
      </p>
    </div>
  );
}
