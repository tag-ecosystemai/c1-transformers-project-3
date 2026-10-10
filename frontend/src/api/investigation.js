// Consumes the backend investigation stream and converts its events
// into the frontend shipment fields used by React components.

import {
  apiUrl,
} from "./base.js";

const NA = "Not available";
const FAILED = "Investigation failed";




export class ApiError extends Error {
  constructor(
    status,
    message,
    detail,
    code,
  ) {
    super(message);

    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.code = code;
  }
}


const MESSAGES = {
  investigation_not_required:
    "Low risk — no investigation needed",

  shipment_not_found:
    "Shipment not found",

  investigation_failed:
    "Investigation failed",

  404:
    "Shipment not found",
};


const messageFor = (
  code,
  status,
) => (
  MESSAGES[code]
  || MESSAGES[status]
  || FAILED
);


const malformed = () =>
  new ApiError(
    0,
    FAILED,
    (
      "The server sent a response "
      + "that could not be understood."
    ),
  );


const isObject = (
  value,
) => (
  value !== null
  && typeof value === "object"
  && !Array.isArray(value)
);


const capitalize = (
  value,
) => {
  const text = String(
    value ?? "",
  )
    .replace(/_/g, " ")
    .toLowerCase();

  return (
    text.charAt(0).toUpperCase()
    + text.slice(1)
  );
};


const percent = (
  probability,
) => {
  const value = Number(
    probability,
  );

  if (!Number.isFinite(value)) {
    return NA;
  }

  return `${(
    value * 100
  ).toFixed(1)}%`;
};


async function* readEvents(
  body,
) {
  const reader = body.getReader();
  const decoder = new TextDecoder();

  let buffer = "";

  try {
    for (;;) {
      const {
        value,
        done,
      } = await reader.read();

      if (done) {
        return;
      }

      buffer = (
        buffer
        + decoder.decode(
          value,
          {
            stream: true,
          },
        )
      ).replace(
        /\r\n/g,
        "\n",
      );

      let eventEnd;

      while (
        (
          eventEnd = buffer.indexOf(
            "\n\n",
          )
        ) !== -1
      ) {
        const block = buffer.slice(
          0,
          eventEnd,
        );

        buffer = buffer.slice(
          eventEnd + 2,
        );

        let event = "message";
        const dataLines = [];

        for (
          const line
          of block.split("\n")
        ) {
          if (
            line.startsWith("event:")
          ) {
            event = line
              .slice(6)
              .trim();
          } else if (
            line.startsWith("data:")
          ) {
            dataLines.push(
              line
                .slice(5)
                .replace(/^ /, ""),
            );
          }
        }

        // Ignore comments and keep-alive blocks.
        if (dataLines.length) {
          yield {
            event,
            data: dataLines.join("\n"),
          };
        }
      }
    }
  } finally {
    reader
      .cancel()
      .catch(() => {});
  }
}


const toEvidence = (
  toolCall,
) => ({
  tool:
    toolCall.tool
    ?? toolCall.name,

  input:
    toolCall.input
    ?? {},

  output:
    toolCall.status === "error"
      ? toolCall.error
      : toolCall.output,

  status:
    toolCall.status,
});


const uniqueStrings = (
  values,
) => {
  if (!Array.isArray(values)) {
    return [];
  }

  return [
    ...new Set(
      values
        .filter(
          (value) =>
            typeof value === "string"
            && value.trim(),
        )
        .map(
          (value) =>
            value.trim(),
        ),
    ),
  ];
};


const citationTitle = (
  filename,
) => String(
  filename,
)
  .replace(
    /\.pdf$/i,
    "",
  )
  .replace(
    /^\d+_/,
    "",
  )
  .replace(
    /_/g,
    " ",
  )
  .replace(
    /\b\w/g,
    (character) =>
      character.toUpperCase(),
  );

const frontendText = (
  value,
) => String(
  value ?? "",
)
  .replace(
    /\bsynthetic\s+/gi,
    "",
  )
  .replace(
    /\b(?:supplier|inventory) records are demonstration data(?: and)?\.?\s*/gi,
    "",
  )
  .replace(
    /\s{2,}/g,
    " ",
  )
  .trim();

 const visibleLimitations = (
  values,
) => uniqueStrings(
  values,
)
  .filter(
    (limitation) => (
      !(
        /supplier records, inventory records/i.test(
          limitation,
        )
        && /operational procedures/i.test(
          limitation,
        )
        && /demonstration data/i.test(
          limitation,
        )
      )
    ),
  )
  .map(
    frontendText,
  );

const toRecommendation = (
  action,
  index,
  shipmentId,
  documentsRetrieved,
) => ({
  id:
    `${shipmentId}-${index + 1}`,

  title:
    frontendText(
      action,
    ),

  // A recommendation only claims retrieved guidance when supporting
  // documents were actually retrieved for the briefing.
  detail:
    documentsRetrieved
      ? (
        "Generated from the collected "
        + "evidence and retrieved "
        + "operational guidance."
      )
      : (
        "Generated from the collected "
        + "evidence only. No supporting "
        + "documents were retrieved."
      ),

  cost:
    null,

  time:
    null,

  risk:
    null,

  source:
    documentsRetrieved
      ? "Grounded disruption briefing"
      : "Evidence-only disruption briefing",
});


// The limitation the backend reports when supporting documents could
// not be retrieved at all. Any other briefing without citations is one
// whose search found nothing to cite.
const RETRIEVAL_UNAVAILABLE =
  /supporting document retrieval was unavailable/i;

export const RETRIEVAL_NOTICES = {
  unavailable: {
    title:
      "Supporting documents unavailable",

    message:
      (
        "Supporting documents could not be retrieved, so this "
        + "briefing cites no operational procedures. It is based "
        + "only on the evidence collected by the investigation."
      ),
  },

  none: {
    title:
      "No supporting documents retrieved",

    message:
      (
        "No supporting operational documents were retrieved for "
        + "this shipment, so this briefing cites no operational "
        + "procedures. It is based only on the evidence collected "
        + "by the investigation."
      ),
  },
};


// Whether the briefing is supported by retrieved documents. Citations
// are the only evidence of retrieval: an empty list is never reported
// as a successful search.
const toRetrieval = (
  citations,
  limitations,
) => {
  if (citations.length > 0) {
    return {
      status:
        "retrieved",

      title:
        null,

      message:
        null,
    };
  }

  const status = (
    limitations.some(
      (limitation) =>
        RETRIEVAL_UNAVAILABLE.test(
          limitation,
        ),
    )
      ? "unavailable"
      : "none"
  );

  return {
    status,
    ...RETRIEVAL_NOTICES[status],
  };
};


function validateDonePayload(
  briefing,
) {
  if (
    !isObject(briefing)
    || typeof briefing.shipment_id
      !== "string"
    || typeof briefing.risk_level
      !== "string"
    || typeof briefing.delay_probability
      !== "number"
    || typeof briefing.summary
      !== "string"
    || !isObject(
      briefing.evidence,
    )
    || !Array.isArray(
      briefing.tool_trace,
    )
    || !Array.isArray(
      briefing.recommended_actions,
    )
    || !Array.isArray(
      briefing.rag_policy_citations,
    )
    || !Array.isArray(
      briefing.limitations,
    )
  ) {
    throw malformed();
  }
}

// The product-level inventory record, as the backend reports it in
// the trace of its inventory step. The record describes the product,
// not the shipment: the backend sends no warehouse, supplier, reorder
// point, replenishment date or destination match, and none is shown.
const toInventoryRecord = (
  toolTrace,
) => {
  const value = toolTrace.find(
    (call) =>
      (call.tool ?? call.name)
        === "get_inventory_coverage"
      && call.status === "success",
  )?.output;

  if (!isObject(value)) {
    return null;
  }

  return {
    productName:
      value.product_name
      ?? null,

    currentStock:
      value.current_stock
      ?? null,

    reservedStock:
      value.reserved_stock
      ?? null,

    availableStock:
      value.available_stock
      ?? null,

    dailyDemand:
      value.daily_demand
      ?? null,

    safetyStock:
      value.safety_stock
      ?? null,

    incomingQuantity:
      value.incoming_quantity
      ?? null,

    inventoryCoverageDays:
      value.inventory_coverage_days
      ?? null,

    stockoutRisk:
      value.stockout_risk
      ?? null,

    belowSafetyStock:
      value.below_safety_stock
      ?? false,

    limitation:
      value.limitation
      ?? null,
  };
};

const formatDays = (
  value,
) => {
  const numberValue = Number(
    value,
  );

  if (!Number.isFinite(
    numberValue,
  )) {
    return NA;
  }

  return `${numberValue.toLocaleString(
    undefined,
    {
      maximumFractionDigits: 2,
    },
  )} days`;
};

function toResult(
  briefing,
) {
  validateDonePayload(
    briefing,
  );

  const toolTrace = (
    briefing.tool_trace
      .map(toEvidence)
  );

  const inventoryRecord = (
    toInventoryRecord(
      briefing.tool_trace,
    )
  );

  const structuredEvidence = {
    shipmentSummary:
      briefing.evidence
        .shipment_summary
      ?? null,

    historicalDelaySummary:
      briefing.evidence
        .historical_delay_summary
      ?? null,

    weatherSummary:
      briefing.evidence
        .weather_summary
      ?? null,

    supplierStatus:
      briefing.evidence
        .supplier_status
      ?? null,

    inventorySummary:
      briefing.evidence
        .inventory_summary
      ?? null,

    inventoryRecord,

    // The whole-day field stays empty when coverage is fractional, so
    // the coverage on the record is preferred.
    inventoryCoverageDays:
      (
        inventoryRecord
          ?.inventoryCoverageDays
        ?? briefing.evidence
          .inventory_coverage_days
        ?? null
      ),
  };

  const cause = [
    structuredEvidence
      .historicalDelaySummary,

    structuredEvidence
      .weatherSummary,

    structuredEvidence
      .supplierStatus,

    structuredEvidence
      .inventorySummary,
  ]
    .filter(Boolean)
    .join(" ");

  const actions = uniqueStrings(
    briefing.recommended_actions,
  );

  const citations = uniqueStrings(
    briefing.rag_policy_citations,
  );

  const limitations = visibleLimitations(
    briefing.limitations,
  );

  const retrieval = toRetrieval(
    citations,
    uniqueStrings(
      briefing.limitations,
    ),
  );

  const citationCards = citations.map(
    (filename) => ({
      filename,

      title:
        citationTitle(
          filename,
        ),

      sourceType:
        "Operational guidance",
    }),
  );

  const recommendations = actions.map(
    (
      action,
      index,
    ) =>
      toRecommendation(
        action,
        index,
        briefing.shipment_id,
        retrieval.status === "retrieved",
      ),
  );

  const inventoryImpact = (
    inventoryRecord
  )
    ? (
      `${formatDays(
        inventoryRecord
          .inventoryCoverageDays,
      )} of coverage on the product's inventory record`
      + ` · ${capitalize(
        inventoryRecord
          .stockoutRisk,
      )} stockout risk on record`
      + ` · ${inventoryRecord
        .availableStock} units available.`
      + " Stock availability for this shipment "
      + "has not been verified."
    )
    : (
      structuredEvidence
        .inventorySummary
      ?? (
        structuredEvidence
          .inventoryCoverageDays
        !== null
          ? (
            "Inventory coverage is "
            + formatDays(
              structuredEvidence
                .inventoryCoverageDays,
            )
            + "."
          )
          : (
            "Inventory impact cannot be "
            + "confirmed because no inventory "
            + "record is available."
          )
      )
    );

  return {
    shipmentId:
      briefing.shipment_id,

    riskLevel:
      briefing.risk_level
        .toLowerCase(),

    delayProbability:
      briefing.delay_probability,

    requiresInvestigation:
      true,

    investigationStatus:
      "complete",

    // Compatibility field used by the current Investigation component.
    evidence:
      toolTrace,

    toolTrace,

    structuredEvidence,

    conclusion:
      frontendText(
        briefing.summary,
      ),

    briefing: {
      summary:
        frontendText(
          briefing.summary,
        ),

      cause:
        cause || NA,

      impact:
        inventoryImpact,

      actions:
        actions
          .map(frontendText)
          .join(" "),

      recommendedActions:
        actions.map(
          frontendText,
        ),

      citations,

      citationCards,

      limitations,

      retrieval,

      generatedAt:
        new Date()
          .toLocaleString(),
    },

    recommendations,

    recommendedActions:
      actions.map(
        frontendText,
      ),

    recommendationsPending:
      false,

    ragPolicyCitations:
      citations,

    citationCards,

    limitations,

    retrieval,

    rawBriefing:
      briefing,
  };
}


function lowRiskDetail(
  evidence,
) {
  const risk = evidence.find(
    (item) =>
      item.tool === "get_delay_risk"
      && item.status === "success",
  )?.output;

  if (
    typeof risk?.shipment_id
      !== "string"
    || typeof risk
      ?.delay_probability
      !== "number"
  ) {
    return null;
  }

  return (
    `Shipment ${risk.shipment_id} `
    + "has a low risk of delay "
    + `(${percent(
      risk.delay_probability,
    )}) and does not require `
    + "further investigation."
  );
}


export async function investigate(
  id,
  onUpdate,
  {
    signal,
    fetch: fetchFn = fetch,
  } = {},
) {
  let response;

  try {
    response = await fetchFn(
      apiUrl(
        (
          "/api/agent/investigate/"
          + `${encodeURIComponent(id)}`
          + "/stream"
        ),
      ),
      {
        method:
          "GET",

        headers: {
          Accept:
            "text/event-stream",
        },

        signal,
      },
    );
  } catch (error) {
    if (signal?.aborted) {
      throw error;
    }

    throw new ApiError(
      0,
      FAILED,
      "The backend could not be reached.",
    );
  }

  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({}));

    const detail = (
      typeof body.detail === "string"
        ? body.detail
        : undefined
    );

    throw new ApiError(
      response.status,
      messageFor(
        body.code,
        response.status,
      ),
      detail,
      body.code,
    );
  }

  const contentType = (
    response.headers.get(
      "content-type",
    )
    || ""
  );

  if (
    !response.body
    || !contentType.includes(
      "text/event-stream",
    )
  ) {
    throw malformed();
  }

  let evidence = [];

  const update = (
    patch,
  ) => {
    if (
      typeof onUpdate
      === "function"
    ) {
      onUpdate(patch);
    }
  };

  const finishTool = (
    data,
  ) => {
    const completedCall = (
      toEvidence(
        data,
      )
    );

    const lastIndex = (
      evidence.length - 1
    );

    const lastEntry = (
      evidence[lastIndex]
    );

    if (
      lastEntry?.tool
        === completedCall.tool
      && lastEntry.status
        === "running"
    ) {
      evidence = [
        ...evidence.slice(
          0,
          lastIndex,
        ),
        completedCall,
      ];
    } else {
      evidence = [
        ...evidence,
        completedCall,
      ];
    }

    update({
      evidence,
      toolTrace:
        evidence,
    });
  };

  try {
    for await (
      const {
        event,
        data: rawData,
      }
      of readEvents(
        response.body,
      )
    ) {
      let data;

      try {
        data = JSON.parse(
          rawData,
        );
      } catch {
        throw malformed();
      }

      if (!isObject(data)) {
        throw malformed();
      }

      if (
        event === "tool_start"
      ) {
        if (
          typeof data.name
          !== "string"
        ) {
          throw malformed();
        }

        evidence = [
          ...evidence,
          {
            tool:
              data.name,

            input:
              data.input
              ?? {},

            status:
              "running",
          },
        ];

        update({
          investigationStatus:
            "running",

          evidence,

          toolTrace:
            evidence,
        });
      } else if (
        event === "tool_complete"
        || event === "tool_error"
      ) {
        if (
          typeof data.name
          !== "string"
        ) {
          throw malformed();
        }

        finishTool({
          ...data,

          status:
            event === "tool_error"
              ? "error"
              : "success",
        });
      } else if (
        event === "message"
      ) {
        if (
          typeof data.content
          !== "string"
        ) {
          throw malformed();
        }

        update({
          conclusion:
            data.content,

          investigationStatus:
            "generating_briefing",
        });
      } else if (
        event === "done"
      ) {
        const result = (
          toResult(
            data,
          )
        );

        update(result);

        return result;
      } else if (
        event === "error"
      ) {
        const detail = (
          typeof data.detail
            === "string"
            ? data.detail
            : undefined
        );

        throw new ApiError(
          typeof data.status
            === "number"
            ? data.status
            : 0,

          messageFor(
            data.code,
            data.status,
          ),

          (
            data.code
              === "investigation_not_required"
            && lowRiskDetail(
              evidence,
            )
          )
          || detail,

          data.code,
        );
      }

      // Unknown event names are ignored so the backend can add
      // new progress events without breaking older frontends.
    }
  } catch (error) {
    if (
      error instanceof ApiError
      || signal?.aborted
    ) {
      throw error;
    }

    throw new ApiError(
      0,
      FAILED,
      (
        "The connection to the "
        + "backend was lost."
      ),
    );
  }

  throw new ApiError(
    0,
    FAILED,
    (
      "The connection closed before "
      + "the investigation finished."
    ),
  );
}


export function failureDetail(
  error,
) {
  if (
    error.status === 0
    || error.code
      === "investigation_not_required"
    || error.code
      === "shipment_not_found"
  ) {
    return error.detail;
  }

  if (error.status === 404) {
    return undefined;
  }

  return (
    "Something went wrong while "
    + "investigating this shipment. "
    + "Please try again."
  );
}


const HIGHEST_FACTOR = {
  product:
    "Product",

  market:
    "Market",

  shipping_mode:
    "Shipping mode",
};


const supplierFinding = (
  output,
) => {
  const supplier = (
    output?.recommended_supplier
  );

  if (!supplier) {
    const candidateCount = Number(
      output?.candidate_count,
    );

    if (
      Number.isFinite(
        candidateCount,
      )
      && candidateCount > 0
    ) {
      return (
        `${candidateCount} comparison `
        + (
          candidateCount === 1
            ? "candidate"
            : "candidates"
        )
        + " found; human review required"
      );
    }

    return (
      "No suitable synthetic "
      + "supplier candidate found"
    );
  }

  return (
    `${supplier.supplier_name} `
    + `· ${supplier.supplier_country} `
    + `· ${capitalize(
      supplier.supplier_risk_level,
    )} risk`
  );
};

const inventoryFinding = (
  output,
) => {
  if (!isObject(output)) {
    return null;
  }

  const coverage = Number(
    output.inventory_coverage_days,
  );

  const risk = capitalize(
    output.stockout_risk,
  );

  if (!Number.isFinite(coverage)) {
    return null;
  }

  // The record is product-level, so the finding says "on record"
  // rather than describing stock for this shipment.
  return (
    `${formatDays(coverage)} coverage on record`
    + ` · ${risk} stockout risk`
  );
};

const STEPS = {
  get_delay_risk: {
    label:
      "Assessing delay risk",

    finding: (output) =>
      (
        `${capitalize(
          output.risk_level,
        )} risk · `
        + `${percent(
          output.delay_probability,
        )} probability`
      ),
  },

  get_shipment: {
    label:
      "Checking shipment details",

    finding: (output) =>
      (
        `${output.destination_city}, `
        + `${output.destination_country} `
        + `· ${output.shipping_mode}`
      ),
  },

  get_historical_delay_context: {
    label:
      "Reviewing historical delay patterns",

    finding: (output) => {
      const factor = (
        output
          .highest_delay_rate_factor
      );

      return (
        `${HIGHEST_FACTOR[factor]} `
        + "has the highest historical "
        + "delay rate "
        + `(${percent(
          output
            .historical_delay_rates[
              factor
            ],
        )})`
      );
    },
  },

  get_destination_weather: {
    label:
      "Checking destination weather",

    finding: (output) =>
      (
        `${capitalize(
          output
            .worst_weather_description,
        )} · `
        + `${capitalize(
          output.severity,
        )} severity`
      ),
  },

  find_alternative_supplier: {
    label:
      "Checking alternative suppliers",

    finding:
      supplierFinding,
  },
  get_inventory_coverage: {
    label:
      "Checking the product inventory record",

    finding:
      inventoryFinding,
  },
};


const OTHER_STEP = {
  label:
    "Gathering additional evidence",

  finding:
    () => null,
};


function findingFor(
  step,
  output,
) {
  try {
    const text = step.finding(
      output,
    );

    if (
      typeof text !== "string"
      || /undefined|null|NaN/.test(
        text,
      )
    ) {
      return null;
    }

    return text;
  } catch {
    return null;
  }
}


export function toSteps(
  shipment,
) {
  const running = (
    shipment.investigationStatus
      === "running"
    || shipment.investigationStatus
      === "generating_briefing"
  );

  const toolTrace = (
    shipment.toolTrace
    || shipment.evidence
    || []
  );

  const steps = toolTrace.map(
    (entry) => {
      const step = (
        Object.hasOwn(
          STEPS,
          entry.tool,
        )
      )
        ? STEPS[entry.tool]
        : OTHER_STEP;

      if (
        entry.status === "success"
      ) {
        return {
          tool:
            entry.tool,

          label:
            step.label,

          finding:
            findingFor(
              step,
              entry.output,
            ),

          status:
            "done",
        };
      }

      if (
        entry.status === "running"
        && running
      ) {
        return {
          tool:
            entry.tool,

          label:
            step.label,

          finding:
            null,

          status:
            "running",
        };
      }

      return {
        tool:
          entry.tool,

        label:
          step.label,

        finding:
          (
            "This information could "
            + "not be retrieved."
          ),

        status:
          "failed",
      };
    },
  );

  if (shipment.briefing) {
    steps.push({
      tool:
        "generate_briefing",

      label:
        "Generating disruption briefing",

      finding:
        shipment.briefing.summary,

      status:
        "complete",
    });
  } else if (
    shipment.investigationStatus
      === "generating_briefing"
  ) {
    steps.push({
      tool:
        "generate_briefing",

      label:
        "Generating disruption briefing",

      finding:
        null,

      status:
        "running",
    });
  }

  return steps;
}