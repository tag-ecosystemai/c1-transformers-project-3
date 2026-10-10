// Run with `npm test`.
// Uses Node's built-in test runner and does not require the backend.

import test from "node:test";
import assert from "node:assert/strict";

import {
  ApiError,
  RETRIEVAL_NOTICES,
  failureDetail,
  investigate,
  toSteps,
} from "./investigation.js";


const sse = (
  event,
  data,
) => (
  `event: ${event}\n`
  + `data: ${JSON.stringify(data)}\n\n`
);


const SUPPLIER_RESULT = {
  category:
    "Cleats",

  destination_country:
    "Brasil",

  required_quantity:
    1,

  recommended_supplier: {
    supplier_id:
      "SUP003",

    supplier_name:
      "NorthStar Logistics",

    supplier_country:
      "Bután",

    product_category:
      "Sporting Goods",

    average_lead_time_days:
      8.5,

    on_time_delivery_rate:
      0.877,

    cancellation_rate:
      0.088,

    quality_issue_rate:
      0.066,

    capacity_utilization:
      0.584,

    supplier_risk_score:
      19.68,

    supplier_risk_level:
      "MEDIUM",

    data_source:
      "SYNTHETIC_MVP",
  },

  alternatives: [],

  candidate_count:
    2,

  data_source:
    "SYNTHETIC_MVP",

  quantity_capacity_verified:
    false,

  limitation:
    "Synthetic supplier data requires human validation.",
};

const INVENTORY_SCOPE_LIMITATION = (
  "Inventory record available; stock availability for this "
  + "shipment has not been verified."
);

// The product-level record exactly as the backend records it in the
// trace of its inventory step: no warehouse, supplier, identifiers,
// reorder point, replenishment date or destination match.
const INVENTORY_RESULT = {
  product_name:
    "Trail Running Shoe",

  current_stock:
    400,

  reserved_stock:
    100,

  available_stock:
    300,

  daily_demand:
    48,

  safety_stock:
    200,

  incoming_quantity:
    200,

  inventory_coverage_days:
    6.25,

  stockout_risk:
    "MEDIUM",

  below_safety_stock:
    false,

  matched_on:
    "product_name (exact, ignoring case and accents)",

  data_source:
    "SYNTHETIC_MVP",

  limitation:
    INVENTORY_SCOPE_LIMITATION,
};

const INVENTORY_SUMMARY = (
  "Inventory record for 'Trail Running Shoe': 300 units available "
  + "(400 in stock, 100 reserved) against average demand of 48 "
  + "units per day, about 6.25 days of coverage. 200 units are "
  + "recorded as incoming. Stockout risk on record: MEDIUM. This is "
  + "a product-level record; stock availability for this shipment "
  + "has not been verified."
);

const RETRIEVAL_UNAVAILABLE_LIMITATION = (
  "Supporting document retrieval was unavailable, so this briefing "
  + "cites no operational procedures and is based only on the "
  + "evidence collected by the investigation."
);

const NO_DOCUMENTS_RETRIEVED_LIMITATION = (
  "No supporting operational documents were retrieved for this "
  + "shipment, so this briefing cites no operational procedures and "
  + "is based only on the evidence collected by the investigation."
);

const BRIEFING = {
  shipment_id:
    "SHP-1",

  risk_level:
    "MEDIUM",

  delay_probability:
    0.55,

  evidence: {
    shipment_summary:
      "SHP-1: 1 x test product to Indaial, Brasil.",

    historical_delay_summary:
      "Historical delay rates: product 57.0%.",

    weather_summary:
      "Observed destination weather showed light drizzle "
      + "with low severity.",

    supplier_status:
      "Synthetic alternative supplier candidate: SUP003 "
      + "(NorthStar Logistics), located in Bután; "
      + "supplier risk MEDIUM.",

    inventory_summary:
      INVENTORY_SUMMARY,

    // The whole-day field stays empty: coverage is fractional.
    inventory_coverage_days:
      null,
  },

  rag_policy_citations: [
    "01_shipment_delay_escalation.pdf",
    "02_weather_disruption_sop.pdf",
    "03_supplier_alternative_policy.pdf",
  ],

  summary:
    "Shipment SHP-1 has a medium predicted delay risk. "
    + "Historical delay rates are elevated, while destination "
    + "weather is low severity. The synthetic supplier candidate "
    + "requires human validation.",

  recommended_actions: [
    "Continue active shipment monitoring.",
    "Do not reroute solely on low-severity weather evidence.",
    "Validate the synthetic supplier before considering a change.",
    "Obtain inventory coverage.",
  ],

  tool_trace: [
    {
      tool:
        "get_delay_risk",

      input: {
        shipment_id:
          "SHP-1",
      },

      output: {
        shipment_id:
          "SHP-1",

        risk_level:
          "MEDIUM",

        delay_probability:
          0.55,

        requires_investigation:
          true,
      },

      status:
        "success",

      error:
        null,
    },

    {
      tool:
        "get_destination_weather",

      input: {
        shipment_id:
          "SHP-1",
      },

      output:
        null,

      status:
        "error",

      error:
        "timeout",
    },

    {
      tool:
        "find_alternative_supplier",

      input: {
        category:
          "Cleats",

        destination_country:
          "Brasil",

        required_quantity:
          1,

        limit:
          3,
      },

      output:
        SUPPLIER_RESULT,

      status:
        "success",

      error:
        null,
    },
    {
      tool:
        "get_inventory_coverage",

      input: {
        shipment_id:
          "SHP-1",
      },

      output:
        INVENTORY_RESULT,

      status:
        "success",

      error:
        null,
    },
  ],

  limitations: [
    "Weather evidence represents destination-level conditions.",
    "Supplier records are synthetic demonstration data.",
    INVENTORY_SCOPE_LIMITATION,
  ],
};

const VISIBLE_BRIEFING_SUMMARY = (
  "Shipment SHP-1 has a medium predicted delay risk. "
  + "Historical delay rates are elevated, while destination "
  + "weather is low severity. The supplier candidate "
  + "requires human validation."
);



const VISIBLE_RECOMMENDED_ACTIONS = [
  "Continue active shipment monitoring.",
  "Do not reroute solely on low-severity weather evidence.",
  "Validate the supplier before considering a change.",
  "Obtain inventory coverage.",
];

const SUCCESS = [
  sse(
    "tool_start",
    {
      name:
        "get_delay_risk",

      input: {
        shipment_id:
          "SHP-1",
      },
    },
  ),

  sse(
    "tool_complete",
    {
      name:
        "get_delay_risk",

      input: {
        shipment_id:
          "SHP-1",
      },

      output: {
        shipment_id:
          "SHP-1",

        risk_level:
          "MEDIUM",

        delay_probability:
          0.55,

        requires_investigation:
          true,
      },

      status:
        "success",

      error:
        null,
    },
  ),

  sse(
    "tool_start",
    {
      name:
        "get_destination_weather",

      input: {
        shipment_id:
          "SHP-1",
      },
    },
  ),

  sse(
    "tool_error",
    {
      name:
        "get_destination_weather",

      input: {
        shipment_id:
          "SHP-1",
      },

      output:
        null,

      status:
        "error",

      error:
        "timeout",
    },
  ),

  sse(
    "tool_start",
    {
      name:
        "find_alternative_supplier",

      input: {
        category:
          "Cleats",

        destination_country:
          "Brasil",

        required_quantity:
          1,

        limit:
          3,
      },
    },
  ),

  sse(
    "tool_complete",
    {
      name:
        "find_alternative_supplier",

      input: {
        category:
          "Cleats",

        destination_country:
          "Brasil",

        required_quantity:
          1,

        limit:
          3,
      },

      output:
        SUPPLIER_RESULT,

      status:
        "success",

      error:
        null,
    },
  ),

    sse(
    "tool_start",
    {
      name:
        "get_inventory_coverage",

      input: {
        shipment_id:
          "SHP-1",
      },
    },
  ),

  sse(
    "tool_complete",
    {
      name:
        "get_inventory_coverage",

      input: {
        shipment_id:
          "SHP-1",
      },

      output:
        INVENTORY_RESULT,

      status:
        "success",

      error:
        null,
    },
  ),

  sse(
    "message",
    {
      role:
        "agent",

      content:
        BRIEFING.summary,
    },
  ),

  sse(
    "done",
    BRIEFING,
  ),
];


function fakeFetch(
  chunks,
  {
    status = 200,
    contentType = "text/event-stream",
    failAfter,
  } = {},
) {
  const calls = [];

  const fetchFn = async (
    url,
    options,
  ) => {
    calls.push({
      url,
      options,
    });

    const encoder = (
      new TextEncoder()
    );

    let index = 0;

    const body = new ReadableStream({
      pull(controller) {
        if (
          failAfter !== undefined
          && index === failAfter
        ) {
          controller.error(
            new TypeError(
              "network error",
            ),
          );

          return;
        }

        if (
          index < chunks.length
        ) {
          controller.enqueue(
            encoder.encode(
              chunks[index],
            ),
          );

          index += 1;
        } else {
          controller.close();
        }
      },
    });

    return new Response(
      body,
      {
        status,

        headers: {
          "content-type":
            contentType,
        },
      },
    );
  };

  fetchFn.calls = calls;

  return fetchFn;
}


async function run(
  chunks,
  options,
) {
  const updates = [];

  const fetchFn = (
    typeof chunks === "function"
      ? chunks
      : fakeFetch(
        chunks,
        options,
      )
  );

  try {
    const result = await investigate(
      "SHP-1",

      (patch) => {
        updates.push(
          patch,
        );
      },

      {
        fetch:
          fetchFn,
      },
    );

    return {
      updates,
      result,
      fetchFn,
    };
  } catch (error) {
    return {
      updates,
      error,
      fetchFn,
    };
  }
}


const failed = (
  outcome,
  detail,
) => {
  assert.ok(
    outcome.error
      instanceof ApiError,

    "expected an ApiError",
  );

  assert.equal(
    outcome.result,
    undefined,
  );

  assert.equal(
    outcome.error.message,
    "Investigation failed",
  );

  if (detail) {
    assert.match(
      outcome.error.detail,
      detail,
    );
  }

  assert.ok(
    outcome.updates.every(
      (update) =>
        !update.briefing,
    ),
  );
};


test(
  "requests the investigation stream endpoint",
  async () => {
    const {
      fetchFn,
    } = await run(
      SUCCESS,
    );

    assert.equal(
      fetchFn.calls[0].url,
      "/api/agent/investigate/SHP-1/stream",
    );

    assert.equal(
      fetchFn.calls[0]
        .options
        .method,
      "GET",
    );

    assert.equal(
      fetchFn.calls[0]
        .options
        .headers
        .Accept,
      "text/event-stream",
    );
  },
);


test(
  "updates investigation progress as events arrive",
  async () => {
    const {
      updates,
      result,
    } = await run(
      SUCCESS,
    );

    assert.equal(
      updates[0]
        .investigationStatus,
      "running",
    );

    assert.equal(
      updates[0]
        .evidence[0]
        .tool,
      "get_delay_risk",
    );

    assert.equal(
      updates[0]
        .evidence[0]
        .status,
      "running",
    );

    assert.equal(
      updates[1]
        .evidence[0]
        .status,
      "success",
    );

    assert.equal(
      updates[2]
        .evidence[1]
        .status,
      "running",
    );

    assert.equal(
      updates[3]
        .evidence[1]
        .status,
      "error",
    );

    assert.equal(
      updates[3]
        .evidence[1]
        .output,
      "timeout",
    );

    assert.equal(
      updates[4]
        .evidence[2]
        .tool,
      "find_alternative_supplier",
    );

    assert.equal(
      updates[5]
        .evidence[2]
        .status,
      "success",
    );

    assert.equal(
      updates[8]
        .investigationStatus,
      "generating_briefing",
    );

    assert.equal(
      updates.at(-1),
      result,
    );
  },
);


test(
  "done exposes the complete backend briefing contract",
  async () => {
    const {
      result,
    } = await run(
      SUCCESS,
    );

    assert.equal(
      result.shipmentId,
      "SHP-1",
    );

    assert.equal(
      result.riskLevel,
      "medium",
    );

    assert.equal(
      result.delayProbability,
      0.55,
    );

    assert.equal(
      result.investigationStatus,
      "complete",
    );

    assert.equal(
      result.briefing.summary,
      VISIBLE_BRIEFING_SUMMARY,
    );

    assert.equal(
      result.structuredEvidence
        .historicalDelaySummary,
      BRIEFING.evidence
        .historical_delay_summary,
    );

    assert.equal(
      result.structuredEvidence
        .weatherSummary,
      BRIEFING.evidence
        .weather_summary,
    );

    assert.equal(
      result.structuredEvidence
        .supplierStatus,
      BRIEFING.evidence
        .supplier_status,
    );

    assert.equal(
      result.structuredEvidence
        .inventorySummary,
      INVENTORY_SUMMARY,
    );

    // Fractional coverage is shown as recorded.
    assert.equal(
      result.structuredEvidence
        .inventoryCoverageDays,
      6.25,
    );

    assert.deepEqual(
      result.structuredEvidence
        .inventoryRecord,
      {
        productName:
          "Trail Running Shoe",
        currentStock:
          400,
        reservedStock:
          100,
        availableStock:
          300,
        dailyDemand:
          48,
        safetyStock:
          200,
        incomingQuantity:
          200,
        inventoryCoverageDays:
          6.25,
        stockoutRisk:
          "MEDIUM",
        belowSafetyStock:
          false,
        limitation:
          INVENTORY_SCOPE_LIMITATION,
      },
    );

    assert.equal(
      "inventoryStatus"
        in result.structuredEvidence,
      false,
    );

    assert.equal(
      result.retrieval.status,
      "retrieved",
    );
  },
);


test(
  "done exposes real PDF citations",
  async () => {
    const {
      result,
    } = await run(
      SUCCESS,
    );

    assert.deepEqual(
      result.ragPolicyCitations,
      BRIEFING
        .rag_policy_citations,
    );

    assert.deepEqual(
      result.citationCards.map(
        (
          citation,
        ) =>
          citation.title,
      ),
      [
        "Shipment Delay Escalation",
        "Weather Disruption Sop",
        "Supplier Alternative Policy",
      ],
    );

    assert.ok(
      result.citationCards.every(
        (
          citation,
        ) =>
          citation.sourceType
          === (
            "Operational "
            + "guidance"
          ),
      ),
    );
  },
);


test(
  "done exposes grounded recommendations",
  async () => {
    const {
      result,
    } = await run(
      SUCCESS,
    );

    assert.equal(
      result.recommendationsPending,
      false,
    );

    assert.deepEqual(
      result.recommendedActions,
      VISIBLE_RECOMMENDED_ACTIONS,
    );

    assert.deepEqual(
      result.recommendations.map(
        (
          recommendation,
        ) =>
          recommendation.title,
      ),
      VISIBLE_RECOMMENDED_ACTIONS,
    );

    assert.ok(
      result.recommendations.every(
        (
          recommendation,
        ) =>
          recommendation.source
          === (
            "Grounded disruption "
            + "briefing"
          ),
      ),
    );
  },
);


test(
  "done exposes user-facing operational limitations",
  async () => {
    const {
      result,
    } = await run(
      SUCCESS,
    );

    assert.ok(
      result.limitations.length > 0,
    );

    assert.ok(
      result.limitations.every(
        (limitation) => (
          !/synthetic/i.test(
            limitation,
          )
        ),
      ),
    );

    assert.deepEqual(
      result.briefing.limitations,
      result.limitations,
    );

    assert.ok(
      result.rawBriefing.limitations.some(
        (limitation) => (
          /synthetic/i.test(
            limitation,
          )
        ),
      ),
    );
  },
);


test(
  "inventory impact describes the product record without claiming shipment stock",
  async () => {
    const {
      result,
    } = await run(
      SUCCESS,
    );

    assert.match(
      result.briefing.impact,
      /6\.25 days of coverage on the product's inventory record/i,
    );

    assert.match(
      result.briefing.impact,
      /medium stockout risk on record/i,
    );

    assert.match(
      result.briefing.impact,
      /300 units available/i,
    );

    assert.match(
      result.briefing.impact,
      /stock availability for this shipment has not been verified/i,
    );
  },
);


const viewOf = (
  result,
) => {
  // Everything the components can render: the raw backend payload is
  // kept only for debugging and is never displayed.
  const {
    rawBriefing,
    ...view
  } = result;

  return JSON.stringify(
    view,
  );
};


const withoutInventoryStep = (
  briefing,
) => ({
  ...briefing,
  tool_trace:
    briefing.tool_trace.filter(
      (call) =>
        call.tool
          !== "get_inventory_coverage",
    ),
});


test(
  "inventory summary is used when the record figures are not in the trace",
  async () => {
    const {
      result,
    } = await run(
      [
        sse(
          "done",
          withoutInventoryStep(
            BRIEFING,
          ),
        ),
      ],
    );

    assert.equal(
      result.structuredEvidence
        .inventoryRecord,
      null,
    );

    assert.equal(
      result.structuredEvidence
        .inventorySummary,
      INVENTORY_SUMMARY,
    );

    assert.equal(
      result.structuredEvidence
        .inventoryCoverageDays,
      null,
    );

    assert.equal(
      result.briefing.impact,
      INVENTORY_SUMMARY,
    );
  },
);


test(
  "a failed inventory step leaves inventory impact unconfirmed",
  async () => {
    const briefing = {
      ...BRIEFING,
      evidence: {
        ...BRIEFING.evidence,
        inventory_summary:
          null,
      },
      tool_trace:
        BRIEFING.tool_trace.map(
          (call) =>
            call.tool
              === "get_inventory_coverage"
              ? {
                ...call,
                output:
                  null,
                status:
                  "error",
                error:
                  "No inventory record could be retrieved for this product.",
              }
              : call,
        ),
    };

    const {
      result,
    } = await run(
      [
        sse(
          "done",
          briefing,
        ),
      ],
    );

    assert.equal(
      result.structuredEvidence
        .inventoryRecord,
      null,
    );

    assert.equal(
      result.structuredEvidence
        .inventorySummary,
      null,
    );

    assert.match(
      result.briefing.impact,
      /cannot be confirmed because no inventory record is available/i,
    );
  },
);


test(
  "obsolete nested inventory status and warehouse claims are never displayed",
  async () => {
    const legacyStatus = {
      ...INVENTORY_RESULT,
      warehouse_id:
        "WH-TEST",
      warehouse_location:
        "Sao Paulo",
      warehouse_country:
        "Brazil",
      supplier_id:
        "SUP-TEST",
      reorder_point:
        451,
      expected_replenishment_date:
        "2017-05-08",
      destination_country:
        "Brasil",
      destination_country_match:
        true,
      calculation_verified:
        true,
    };

    const briefing = {
      ...BRIEFING,
      evidence: {
        ...BRIEFING.evidence,
        inventory_status:
          legacyStatus,
      },
      tool_trace:
        BRIEFING.tool_trace.map(
          (call) =>
            call.tool
              === "get_inventory_coverage"
              ? {
                ...call,
                output:
                  legacyStatus,
              }
              : call,
        ),
    };

    const {
      result,
    } = await run(
      [
        sse(
          "done",
          briefing,
        ),
      ],
    );

    const record = (
      result.structuredEvidence
        .inventoryRecord
    );

    assert.deepEqual(
      Object.keys(record).sort(),
      [
        "availableStock",
        "belowSafetyStock",
        "currentStock",
        "dailyDemand",
        "incomingQuantity",
        "inventoryCoverageDays",
        "limitation",
        "productName",
        "reservedStock",
        "safetyStock",
        "stockoutRisk",
      ],
    );

    assert.doesNotMatch(
      JSON.stringify({
        record,
        impact:
          result.briefing.impact,
        summary:
          result.structuredEvidence
            .inventorySummary,
      }),
      /warehouse|WH-TEST|Sao Paulo|reorder|451|2017-05-08|destination|calculation|SUP-TEST/i,
    );
  },
);


const withoutCitations = (
  limitation,
) => ({
  ...BRIEFING,
  rag_policy_citations:
    [],
  limitations: [
    INVENTORY_SCOPE_LIMITATION,
    ...(
      limitation
        ? [limitation]
        : []
    ),
    "Weather evidence represents destination-level conditions.",
  ],
});


test(
  "an empty citation list is a valid briefing and renders no citations",
  async () => {
    const outcome = await run(
      [
        sse(
          "done",
          withoutCitations(
            RETRIEVAL_UNAVAILABLE_LIMITATION,
          ),
        ),
      ],
    );

    assert.equal(
      outcome.error,
      undefined,
    );

    const {
      result,
    } = outcome;

    assert.equal(
      result.investigationStatus,
      "complete",
    );

    assert.deepEqual(
      result.ragPolicyCitations,
      [],
    );

    assert.deepEqual(
      result.citationCards,
      [],
    );

    assert.deepEqual(
      result.briefing.citations,
      [],
    );

    assert.deepEqual(
      result.briefing.citationCards,
      [],
    );

    // No placeholder or previously shown document is listed.
    assert.doesNotMatch(
      viewOf(result),
      /\.pdf|SOP-\d+|Operational guidance"/i,
    );

    // The rest of the briefing is still shown.
    assert.equal(
      result.briefing.summary,
      VISIBLE_BRIEFING_SUMMARY,
    );

    assert.deepEqual(
      result.recommendedActions,
      VISIBLE_RECOMMENDED_ACTIONS,
    );
  },
);


test(
  "unavailable document retrieval is explained and never reported as success",
  async () => {
    const {
      result,
    } = await run(
      [
        sse(
          "done",
          withoutCitations(
            RETRIEVAL_UNAVAILABLE_LIMITATION,
          ),
        ),
      ],
    );

    assert.deepEqual(
      result.retrieval,
      {
        status:
          "unavailable",
        ...RETRIEVAL_NOTICES.unavailable,
      },
    );

    assert.equal(
      result.retrieval.title,
      "Supporting documents unavailable",
    );

    assert.match(
      result.retrieval.message,
      /could not be retrieved, so this briefing cites no operational procedures/i,
    );

    assert.deepEqual(
      result.briefing.retrieval,
      result.retrieval,
    );

    // The backend's own limitation is still listed for the reader.
    assert.ok(
      result.limitations.includes(
        RETRIEVAL_UNAVAILABLE_LIMITATION,
      ),
    );

    assert.ok(
      result.briefing.limitations.includes(
        RETRIEVAL_UNAVAILABLE_LIMITATION,
      ),
    );

    // Recommendations do not claim to rest on retrieved guidance.
    assert.ok(
      result.recommendations.length > 0,
    );

    for (
      const recommendation
      of result.recommendations
    ) {
      assert.equal(
        recommendation.detail,
        "Generated from the collected evidence only. "
        + "No supporting documents were retrieved.",
      );

      assert.equal(
        recommendation.source,
        "Evidence-only disruption briefing",
      );
    }

    assert.doesNotMatch(
      viewOf(result),
      /retrieved operational guidance|Grounded disruption briefing/i,
    );
  },
);


test(
  "a search that found no documents is distinguished from an unavailable one",
  async () => {
    const {
      result,
    } = await run(
      [
        sse(
          "done",
          withoutCitations(
            NO_DOCUMENTS_RETRIEVED_LIMITATION,
          ),
        ),
      ],
    );

    assert.deepEqual(
      result.retrieval,
      {
        status:
          "none",
        ...RETRIEVAL_NOTICES.none,
      },
    );

    assert.equal(
      result.retrieval.title,
      "No supporting documents retrieved",
    );

    assert.ok(
      result.limitations.includes(
        NO_DOCUMENTS_RETRIEVED_LIMITATION,
      ),
    );
  },
);


test(
  "an empty citation list without a stated reason is still not a success",
  async () => {
    const {
      result,
    } = await run(
      [
        sse(
          "done",
          withoutCitations(
            null,
          ),
        ),
      ],
    );

    assert.equal(
      result.retrieval.status,
      "none",
    );

    assert.equal(
      result.recommendations[0].source,
      "Evidence-only disruption briefing",
    );
  },
);


test(
  "retrieved documents are cited and no retrieval notice is shown",
  async () => {
    const {
      result,
    } = await run(
      SUCCESS,
    );

    assert.deepEqual(
      result.retrieval,
      {
        status:
          "retrieved",
        title:
          null,
        message:
          null,
      },
    );

    assert.deepEqual(
      result.ragPolicyCitations,
      BRIEFING.rag_policy_citations,
    );

    assert.equal(
      result.citationCards.length,
      3,
    );

    for (
      const recommendation
      of result.recommendations
    ) {
      assert.equal(
        recommendation.detail,
        "Generated from the collected evidence and "
        + "retrieved operational guidance.",
      );

      assert.equal(
        recommendation.source,
        "Grounded disruption briefing",
      );
    }
  },
);


test(
  "handles events split across chunks and CRLF endings",
  async () => {
    const text = SUCCESS
      .join("")
      .replace(
        /\n/g,
        "\r\n",
      );

    const chunks = [];

    for (
      let index = 0;
      index < text.length;
      index += 7
    ) {
      chunks.push(
        text.slice(
          index,
          index + 7,
        ),
      );
    }

    const {
      result,
    } = await run(
      chunks,
    );

    assert.equal(
      result.briefing.summary,
      VISIBLE_BRIEFING_SUMMARY,
    );
  },
);


test(
  "ignores keep-alives and unknown events",
  async () => {
    const {
      result,
    } = await run(
      [
        ": keep-alive\n\n",

        sse(
          "heartbeat",
          {
            sequence:
              1,
          },
        ),

        ...SUCCESS,
      ],
    );

    assert.equal(
      result.briefing.summary,
      VISIBLE_BRIEFING_SUMMARY,
    );
  },
);


const OUTPUTS = {
  get_delay_risk: {
    shipment_id:
      "SHP-1",

    delay_probability:
      0.4033,

    risk_level:
      "MEDIUM",

    requires_investigation:
      true,
  },

  get_shipment: {
    shipment_reference:
      "SHP-1",

    destination_city:
      "Indaial",

    destination_country:
      "Brasil",

    shipping_mode:
      "Standard Class",
  },

  get_historical_delay_context: {
    historical_delay_rates: {
      product:
        0.57,

      market:
        0.55,

      shipping_mode:
        0.38,
    },

    highest_delay_rate_factor:
      "product",
  },

  get_destination_weather: {
    worst_weather_description:
      "light drizzle",

    severity:
      "low",
  },

  find_alternative_supplier:
    SUPPLIER_RESULT,
  get_inventory_coverage:
    INVENTORY_RESULT,
};


const TOOLS = Object.keys(
  OUTPUTS,
);


const evidenceFor = (
  tools,
) => tools.map(
  (
    tool,
  ) => ({
    tool,

    input:
      tool === "find_alternative_supplier"
        ? {
          category:
            "Cleats",

          destination_country:
            "Brasil",

          required_quantity:
            1,

          limit:
            3,
        }
        : tool === "get_inventory_coverage"
          ? {
            shipment_id:
          "SHP-1",
          }
          : {
            shipment_id:
              "SHP-1",
          },

    output:
      OUTPUTS[tool],

    status:
      "success",
  }),
);


const visible = (
  steps,
) => steps.map(
  (
    step,
  ) => (
    `${step.label} `
    + `${step.finding ?? ""}`
  ),
).join("\n");


const assertNoInternals = (
  steps,
) => {
  const internalPattern =
    /get_|shipment_id|[{}\[\]"]|undefined|null|NaN/i;

  assert.doesNotMatch(
    visible(steps),
    internalPattern,
  );
};


test(
  "toSteps presents every backend tool with a friendly label",
  () => {
    const steps = toSteps({
      investigationStatus:
        "running",

      evidence:
        evidenceFor(
          TOOLS,
        ),
    });

    assert.deepEqual(
      steps,
      [
        {
          tool:
            "get_delay_risk",

          label:
            "Assessing delay risk",

          finding:
            "Medium risk · 40.3% probability",

          status:
            "done",
        },

        {
          tool:
            "get_shipment",

          label:
            "Checking shipment details",

          finding:
            (
              "Indaial, Brasil "
              + "· Standard Class"
            ),

          status:
            "done",
        },

        {
          tool:
            "get_historical_delay_context",

          label:
            (
              "Reviewing historical "
              + "delay patterns"
            ),

          finding:
            (
              "Product has the highest "
              + "historical delay rate "
              + "(57.0%)"
            ),

          status:
            "done",
        },

        {
          tool:
            "get_destination_weather",

          label:
            (
              "Checking destination "
              + "weather"
            ),

          finding:
            (
              "Light drizzle "
              + "· Low severity"
            ),

          status:
            "done",
        },

        {
          tool:
            "find_alternative_supplier",

          label:
            (
              "Checking alternative "
              + "suppliers"
            ),

          finding:
            (
              "NorthStar Logistics "
              + "· Bután · Medium risk"
            ),

          status:
            "done",
        },
        {
          tool:
            "get_inventory_coverage",

          label:
            "Checking the product inventory record",

          finding:
            (
              "6.25 days coverage on record "
              + "· Medium stockout risk"
            ),

          status:
            "done",
        },
      ],
    );

    assertNoInternals(
      steps,
    );
  },
);


test(
  "toSteps shows a running tool without a finding",
  () => {
    const evidence = [
      ...evidenceFor(
        [
          "get_delay_risk",
        ],
      ),

      {
        tool:
          "get_shipment",

        input:
          {},

        status:
          "running",
      },
    ];

    const steps = toSteps({
      investigationStatus:
        "running",

      evidence,
    });

    assert.deepEqual(
      steps[1],
      {
        tool:
          "get_shipment",

        label:
          "Checking shipment details",

        finding:
          null,

        status:
          "running",
      },
    );
  },
);


test(
  "toSteps hides internal error details",
  () => {
    const [
      step,
    ] = toSteps({
      investigationStatus:
        "running",

      evidence: [
        {
          tool:
            "get_destination_weather",

          input:
            {},

          output:
            "HTTPSConnectionPool: internal failure",

          status:
            "error",
        },
      ],
    });

    assert.deepEqual(
      step,
      {
        tool:
          "get_destination_weather",

        label:
          "Checking destination weather",

        finding:
          "This information could not be retrieved.",

        status:
          "failed",
      },
    );
  },
);


test(
  "toSteps closes with the generated briefing",
  () => {
    const evidence = evidenceFor(
      TOOLS,
    );

    const generating = toSteps({
      investigationStatus:
        "generating_briefing",

      evidence,

      conclusion:
        "Draft summary",
    });

    assert.deepEqual(
      generating.at(-1),
      {
        tool:
          "generate_briefing",

        label:
          "Generating disruption briefing",

        finding:
          null,

        status:
          "running",
      },
    );

    const done = toSteps({
      investigationStatus:
        "complete",

      evidence,

      briefing: {
        summary:
          "Final grounded summary.",
      },
    });

    assert.deepEqual(
      done.at(-1),
      {
        tool:
          "generate_briefing",

        label:
          "Generating disruption briefing",

        finding:
          "Final grounded summary.",

        status:
          "complete",
      },
    );
  },
);


test(
  "unknown tools never expose internal names",
  () => {
    const steps = toSteps({
      investigationStatus:
        "running",

      evidence: [
        {
          tool:
            "internal_private_tool",

          input:
            {},

          output: {
            secret:
              true,
          },

          status:
            "success",
        },
      ],
    });

    assert.equal(
      steps[0].label,
      "Gathering additional evidence",
    );

    assert.equal(
      steps[0].finding,
      null,
    );

    assertNoInternals(
      steps,
    );
  },
);


test(
  "failureDetail preserves user-facing errors and hides internal errors",
  () => {
    assert.equal(
      failureDetail(
        new ApiError(
          400,
          "message",
          "Shipment SHP-1 is LOW risk",
          "investigation_not_required",
        ),
      ),
      "Shipment SHP-1 is LOW risk",
    );

    assert.equal(
      failureDetail(
        new ApiError(
          0,
          "message",
          "The backend could not be reached.",
        ),
      ),
      "The backend could not be reached.",
    );

    assert.doesNotMatch(
      failureDetail(
        new ApiError(
          500,
          "message",
          "KeyError('internal')",
          "investigation_failed",
        ),
      ),
      /KeyError|internal/,
    );
  },
);


const LOW_RISK_ERROR = sse(
  "error",
  {
    status:
      400,

    code:
      "investigation_not_required",

    detail:
      (
        "Shipment SHP-153440 is LOW risk "
        + "(0.3985) and does not require "
        + "AI investigation."
      ),
  },
);


test(
  "reports low-risk shipments as not requiring investigation",
  async () => {
    const outcome = await run(
      [
        sse(
          "tool_start",
          {
            name:
              "get_delay_risk",

            input: {
              shipment_id:
                "SHP-153440",
            },
          },
        ),

        sse(
          "tool_complete",
          {
            name:
              "get_delay_risk",

            input: {
              shipment_id:
                "SHP-153440",
            },

            output: {
              shipment_id:
                "SHP-153440",

              delay_probability:
                0.3985,

              risk_level:
                "LOW",

              requires_investigation:
                false,
            },

            status:
              "success",

            error:
              null,
          },
        ),

        LOW_RISK_ERROR,
      ],
    );

    assert.equal(
      outcome.error.code,
      "investigation_not_required",
    );

    assert.equal(
      outcome.error.message,
      (
        "Low risk — no "
        + "investigation needed"
      ),
    );

    assert.equal(
      outcome.error.detail,
      (
        "Shipment SHP-153440 has "
        + "a low risk of delay "
        + "(39.9%) and does not "
        + "require further investigation."
      ),
    );
  },
);


test(
  "unknown shipment errors receive a friendly message",
  async () => {
    const outcome = await run(
      [
        sse(
          "error",
          {
            status:
              404,

            code:
              "shipment_not_found",

            detail:
              "not found",
          },
        ),
      ],
    );

    assert.equal(
      outcome.error.message,
      "Shipment not found",
    );

    assert.equal(
      outcome.error.status,
      404,
    );
  },
);


for (
  const [
    status,
    message,
  ]
  of [
    [
      400,
      "Investigation failed",
    ],

    [
      404,
      "Shipment not found",
    ],

    [
      500,
      "Investigation failed",
    ],
  ]
) {
  test(
    `HTTP ${status} is a failure`,
    async () => {
      const outcome = await run(
        [
          JSON.stringify({
            detail:
              "server said no",
          }),
        ],
        {
          status,
          contentType:
            "application/json",
        },
      );

      assert.ok(
        outcome.error
          instanceof ApiError,
      );

      assert.equal(
        outcome.error.status,
        status,
      );

      assert.equal(
        outcome.error.message,
        message,
      );

      assert.equal(
        outcome.error.detail,
        "server said no",
      );
    },
  );
}


test(
  "connection failures are reported",
  async () => {
    const outcome = await run(
      async () => {
        throw new TypeError(
          "fetch failed",
        );
      },
    );

    failed(
      outcome,
      /could not be reached/,
    );
  },
);


test(
  "non-SSE success responses fail cleanly",
  async () => {
    const outcome = await run(
      [
        JSON.stringify(
          BRIEFING,
        ),
      ],
      {
        contentType:
          "application/json",
      },
    );

    failed(
      outcome,
      /could not be understood/,
    );
  },
);


test(
  "streams ending before done fail",
  async () => {
    const outcome = await run(
      SUCCESS.slice(
        0,
        6,
      ),
    );

    failed(
      outcome,
      /closed before/,
    );
  },
);


test(
  "connection drops during the stream fail cleanly",
  async () => {
    const outcome = await run(
      SUCCESS,
      {
        failAfter:
          2,
      },
    );

    failed(
      outcome,
      /connection to the backend was lost/,
    );
  },
);


test(
  "malformed JSON events fail",
  async () => {
    const outcome = await run(
      [
        SUCCESS[0],

        (
          "event: tool_complete\n"
          + "data: {not json\n\n"
        ),
      ],
    );

    failed(
      outcome,
      /could not be understood/,
    );
  },
);


test(
  "done events missing required fields fail",
  async () => {
    const {
      tool_trace,
      ...incomplete
    } = BRIEFING;

    const outcome = await run(
      [
        sse(
          "done",
          incomplete,
        ),
      ],
    );

    failed(
      outcome,
      /could not be understood/,
    );
  },
);


test(
  "abort stops the investigation without converting it to ApiError",
  async () => {
    const controller = (
      new AbortController()
    );

    const updates = [];

    const fetchFn = async (
      url,
      {
        signal,
      },
    ) => {
      const encoder = (
        new TextEncoder()
      );

      const body = new ReadableStream({
        start(streamController) {
          streamController.enqueue(
            encoder.encode(
              SUCCESS[0],
            ),
          );

          signal.addEventListener(
            "abort",
            () => {
              streamController.error(
                signal.reason,
              );
            },
          );
        },
      });

      return new Response(
        body,
        {
          headers: {
            "content-type":
              "text/event-stream",
          },
        },
      );
    };

    const pending = investigate(
      "SHP-1",

      (patch) => {
        updates.push(
          patch,
        );

        controller.abort();
      },

      {
        signal:
          controller.signal,

        fetch:
          fetchFn,
      },
    );

    await assert.rejects(
      pending,
      (
        error,
      ) => (
        !(error instanceof ApiError)
        && error.name
          === "AbortError"
      ),
    );

    assert.equal(
      updates.length,
      1,
    );
  },
);
