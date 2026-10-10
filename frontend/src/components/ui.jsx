export const NA = "Not available";


const isNumber = (
  value,
) => (
  typeof value === "number"
  && Number.isFinite(value)
);


export const pct = (
  probability,
) => (
  isNumber(probability)
    ? `${Math.round(
      probability * 100,
    )}%`
    : NA
);


export const precisePct = (
  probability,
) => (
  isNumber(probability)
    ? `${(
      probability * 100
    ).toFixed(1)}%`
    : NA
);


export const money = (
  value,
) => (
  isNumber(value)
    ? `$${value.toLocaleString()}`
    : NA
);


export const number = (
  value,
  digits = 1,
) => (
  isNumber(value)
    ? value.toFixed(digits)
    : NA
);


export const titleCase = (
  value,
) => {
  const text = String(
    value ?? "",
  )
    .replace(/_/g, " ")
    .trim()
    .toLowerCase();

  if (!text) {
    return NA;
  }

  return text.replace(
    /\b\w/g,
    (character) =>
      character.toUpperCase(),
  );
};


export const RiskBadge = ({
  level,
}) => {
  const normalizedLevel = String(
    level || "unknown",
  ).toLowerCase();

  return (
    <span
      className={
        `badge ${normalizedLevel}`
      }
    >
      {titleCase(
        normalizedLevel,
      )}
    </span>
  );
};


const STATUS_LABELS = {
  none:
    "Not started",

  running:
    "Investigating",

  generating_briefing:
    "Generating briefing",

  complete:
    "Complete",

  not_required:
    "Not required",

  failed:
    "Failed",
};


export const StatusChip = ({
  status,
}) => {
  const normalizedStatus = String(
    status || "none",
  ).toLowerCase();

  const label = (
    STATUS_LABELS[
      normalizedStatus
    ]
    || titleCase(
      normalizedStatus,
    )
  );

  return (
    <span
      className={
        `chip ${normalizedStatus}`
      }
    >
      {label}
    </span>
  );
};


export const Meter = ({
  value,
  level,
}) => {
  const normalizedLevel = String(
    level || "unknown",
  ).toLowerCase();

  const width = isNumber(value)
    ? `${Math.max(
      0,
      Math.min(
        value * 100,
        100,
      ),
    )}%`
    : "0%";

  return (
    <div
      className="meter"
      title={pct(value)}
      role="progressbar"
      aria-label="Delay probability"
      aria-valuemin="0"
      aria-valuemax="100"
      aria-valuenow={
        isNumber(value)
          ? Math.round(
            value * 100,
          )
          : 0
      }
    >
      <i
        className={
          normalizedLevel
        }
        style={{
          width,
        }}
      />
    </div>
  );
};


export const Empty = ({
  children,
  tone = "default",
}) => (
  <div
    className={
      tone === "error"
        ? "empty err"
        : "empty"
    }
  >
    {children}
  </div>
);


export const SectionHeading = ({
  eyebrow,
  title,
  description,
}) => (
  <header className="section-heading">
    <div>
      {eyebrow && (
        <small className="eyebrow">
          {eyebrow}
        </small>
      )}

      <h2>{title}</h2>

      {description && (
        <p>{description}</p>
      )}
    </div>
  </header>
);


export const EvidenceCard = ({
  title,
  children,
  tone = "default",
}) => (
  <article
    className={
      `evidence-card ${tone}`
    }
  >
    <h3>{title}</h3>

    <div className="evidence-content">
      {children}
    </div>
  </article>
);