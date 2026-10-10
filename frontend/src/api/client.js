// Talks to the FastAPI backend through Vite's /api proxy and
// converts backend responses into the shipment shape used by React.

import {
  ApiError,
} from "./investigation.js";

import {
  apiUrl,
} from "./base.js";

const NA = "Not available";


const DEMO_SHIPMENTS = (
  import.meta.env.VITE_DEMO_SHIPMENTS
  || "SHP-153444,SHP-153440"
)
  .split(",")
  .map(
    (reference) =>
      reference.trim(),
  )
  .filter(Boolean);


async function request(
  method,
  path,
  messages,
) {
  let response;

  try {
    response = await fetch(
      apiUrl(
        path,
      ),
      {
        method,
        headers: {
          Accept: "application/json",
        },
      },
    );
  } catch {
    throw new ApiError(
      0,
      messages.default,
      "The backend could not be reached.",
    );
  }

  const body = await response
    .json()
    .catch(() => ({}));

  if (!response.ok) {
    const detail = (
      typeof body.detail === "string"
        ? body.detail
        : undefined
    );

    throw new ApiError(
      response.status,
      messages[response.status]
      || messages.default,
      detail,
      body.code,
    );
  }

  return body;
}


function scheduledArrival(
  orderDate,
  scheduledShippingDays,
) {
  const dateText = String(
    orderDate ?? "",
  ).slice(
    0,
    10,
  );

  const start = Date.parse(
    `${dateText}T00:00:00Z`,
  );

  const days = Number(
    scheduledShippingDays,
  );

  if (
    Number.isNaN(start)
    || !Number.isFinite(days)
  ) {
    return NA;
  }

  const arrival = new Date(
    start + days * 86400000,
  );

  return (
    `${arrival.toISOString().slice(0, 10)} `
    + "(scheduled)"
  );
}


function destinationLabel(
  shipment,
) {
  return [
    shipment.destination_city,
    shipment.destination_state,
    shipment.destination_country,
  ]
    .filter(Boolean)
    .join(", ")
    || NA;
}


function historicalDelayEvidence(
  shipment,
) {
  return {
    product:
      shipment
        .historical_product_delay_rate
      ?? null,

    market:
      shipment
        .historical_market_delay_rate
      ?? null,

    shippingMode:
      shipment
        .historical_shipping_mode_delay_rate
      ?? null,
  };
}


export function toShipment(
  shipment,
  prediction,
) {
  const destination = (
    destinationLabel(
      shipment,
    )
  );

  return {
    id:
      shipment.shipment_reference,

    shipmentReference:
      shipment.shipment_reference,

    riskLevel:
      String(
        prediction.risk_level,
      ).toLowerCase(),

    delayProbability:
      prediction.delay_probability,

    requiresInvestigation:
      prediction.requires_investigation,

    investigationStatus:
      "none",

    investigationError:
      null,

    details: {
      product:
        shipment.product_name
        || NA,

      category:
        shipment.category
        || NA,

      department:
        shipment.department
        || NA,

      market:
        shipment.market
        || NA,

      origin:
        NA,

      destination,

      destinationCity:
        shipment.destination_city
        || NA,

      destinationState:
        shipment.destination_state
        || NA,

      destinationCountry:
        shipment.destination_country
        || NA,

      destinationRegion:
        shipment.destination_region
        || NA,

      carrier:
        shipment.shipping_mode
        || NA,

      shippingMode:
        shipment.shipping_mode
        || NA,

      scheduledDays:
        shipment.scheduled_shipping_days
        ?? null,

      eta:
        scheduledArrival(
          shipment.order_date,
          shipment
            .scheduled_shipping_days,
        ),

      orderDate:
        shipment.order_date
        || null,

      status:
        prediction
          .requires_investigation
          ? "Investigation required"
          : "Routine monitoring",

      supplier:
        NA,

      quantity:
        shipment.quantity
        ?? null,

      productPrice:
        shipment.product_price
        ?? null,

      sales:
        shipment.sales
        ?? null,

      discount:
        shipment.discount
        ?? null,
    },

    historicalDelayRates:
      historicalDelayEvidence(
        shipment,
      ),

    coordinates: {
      latitude:
        shipment.latitude
        ?? null,

      longitude:
        shipment.longitude
        ?? null,
    },

    impact:
      null,

    evidence:
      [],

    toolTrace:
      [],

    structuredEvidence:
      null,

    conclusion:
      null,

    briefing:
      null,

    recommendations:
      [],

    recommendedActions:
      [],

    recommendationsPending:
      false,

    ragPolicyCitations:
      [],

    citationCards:
      [],

    limitations:
      [],

    rawShipment:
      shipment,

    rawPrediction:
      prediction,
  };
}


export async function loadShipment(
  reference,
) {
  const messages = {
    404:
      "Shipment not found",

    default:
      "Could not load shipment",
  };

  const encodedReference = (
    encodeURIComponent(
      reference,
    )
  );

  const [
    shipment,
    prediction,
  ] = await Promise.all(
    [
      request(
        "GET",
        (
          "/api/shipments/"
          + encodedReference
        ),
        messages,
      ),

      request(
        "POST",
        (
          "/api/predictions/evaluate/"
          + encodedReference
        ),
        messages,
      ),
    ],
  );

  return toShipment(
    shipment,
    prediction,
  );
}

async function mapWithConcurrency(
  values,
  limit,
  operation,
) {
  const results = new Array(
    values.length,
  );

  let nextIndex = 0;

  async function worker() {
    for (;;) {
      const index = nextIndex;

      nextIndex += 1;

      if (index >= values.length) {
        return;
      }

      try {
        const value = await operation(
          values[index],
        );

        results[index] = {
          status: "fulfilled",
          value,
        };
      } catch (reason) {
        results[index] = {
          status: "rejected",
          reason,
        };
      }
    }
  }

  const workerCount = Math.min(
    limit,
    values.length,
  );

  await Promise.all(
    Array.from(
      {
        length: workerCount,
      },
      () => worker(),
    ),
  );

  return results;
}

export async function getShipments() {
  const results = (
    await mapWithConcurrency(
      DEMO_SHIPMENTS,
      3,
      loadShipment,
    )
  );

  const shipments = results
    .filter(
      (result) =>
        result.status === "fulfilled",
    )
    .map(
      (result) =>
        result.value,
    );

  const failures = results.flatMap(
    (
      result,
      index,
    ) => {
      if (
        result.status !== "rejected"
      ) {
        return [];
      }

      const message = (
        result.reason?.message
        || "Could not load shipment"
      );

      return [
        `${DEMO_SHIPMENTS[index]}: ${message}`,
      ];
    },
  );

  if (!shipments.length) {
    throw new Error(
      failures.join("; ")
      || "No demo shipments configured",
    );
  }

  return {
    shipments,
    failures,
  };
}