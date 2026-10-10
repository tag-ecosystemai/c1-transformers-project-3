import {
  useEffect,
  useMemo,
  useState,
} from "react";

import {
  getShipments,
} from "./api/client.js";

import Actions from "./components/Actions.jsx";
import Briefings from "./components/Briefings.jsx";
import Home from "./components/Home.jsx";
import Investigation from "./components/Investigation.jsx";
import Shipments from "./components/Shipments.jsx";

import {
  RiskBadge,
  StatusChip,
} from "./components/ui.jsx";


const TABS = [
  {
    id: "Home",
    label: "Home",
  },
  {
    id: "Shipments",
    label: "Shipments",
  },
  {
    id: "Investigation",
    label: "Investigation",
  },
  {
    id: "Actions",
    label: "Actions",
  },
  {
    id: "Briefings",
    label: "Briefings",
  },
];


export default function App() {
  const [
    tab,
    setTab,
  ] = useState("Home");

  const [
    shipments,
    setShipments,
  ] = useState([]);

  const [
    selectedId,
    setSelectedId,
  ] = useState(null);

  const [
    decisions,
    setDecisions,
  ] = useState({});

  const [
    error,
    setError,
  ] = useState(null);

  const [
    loadFailures,
    setLoadFailures,
  ] = useState([]);

  const [
    loading,
    setLoading,
  ] = useState(true);

  const [
    reloadKey,
    setReloadKey,
  ] = useState(0);

  useEffect(
    () => {
      let active = true;

      setLoading(true);
      setError(null);
      setLoadFailures([]);

      getShipments()
        .then(
          ({
            shipments:
              loadedShipments,

            failures,
          }) => {
            if (!active) {
              return;
            }

            setShipments(
              loadedShipments,
            );

            setSelectedId(
              (
                currentId,
              ) => {
                const stillAvailable = (
                  loadedShipments.some(
                    (
                      shipment,
                    ) =>
                      shipment.id
                      === currentId,
                  )
                );

                return stillAvailable
                  ? currentId
                  : loadedShipments[0]
                    ?.id
                    ?? null;
              },
            );

            setLoadFailures(
              failures,
            );
          },
        )
        .catch(
          (
            loadError,
          ) => {
            if (!active) {
              return;
            }

            setError(
              loadError.message
              || (
                "The shipment data "
                + "could not be loaded."
              ),
            );
          },
        )
        .finally(
          () => {
            if (active) {
              setLoading(false);
            }
          },
        );

      return () => {
        active = false;
      };
    },
    [
      reloadKey,
    ],
  );

  const selected = useMemo(
    () => (
      shipments.find(
        (
          shipment,
        ) =>
          shipment.id === selectedId,
      )
      || shipments[0]
      || null
    ),
    [
      shipments,
      selectedId,
    ],
  );

  const updateShipment = (
    id,
    patch,
  ) => {
    setShipments(
      (
        currentShipments,
      ) =>
        currentShipments.map(
          (
            shipment,
          ) =>
            shipment.id === id
              ? {
                ...shipment,
                ...patch,
              }
              : shipment,
        ),
    );
  };

  const selectShipment = (
    id,
  ) => {
    setSelectedId(
      id,
    );
  };

  const openShipment = (
    id,
  ) => {
    setSelectedId(
      id,
    );

    setTab(
      "Shipments",
    );
  };

  const investigateShipment = (
    id,
  ) => {
    setSelectedId(
      id,
    );

    setTab(
      "Investigation",
    );
  };

  const reload = () => {
    setReloadKey(
      (
        currentKey,
      ) =>
        currentKey + 1,
    );
  };

  const decide = (
    recommendationId,
    decision,
  ) => {
    setDecisions(
      (
        currentDecisions,
      ) => ({
        ...currentDecisions,

        decision,
      }),
    );
  };

  const showShipmentContext = (
    selected
    && tab !== "Home"
    && tab !== "Shipments"
  );

  return (
    <div className="app">
      <nav
        className="rail"
        aria-label="Control Tower navigation"
      >
        <div className="brand">
          <span>Supply Chain</span>
          Control Tower
        </div>

        <div className="rail-links">
          {TABS.map(
            (
              item,
            ) => (
              <button
                key={
                  item.id
                }
                className={
                  item.id === tab
                    ? "on"
                    : ""
                }
                onClick={() =>
                  setTab(
                    item.id,
                  )
                }
              >
                {item.label}
              </button>
            ),
          )}
        </div>

        <div className="rail-footer">
          <span>
            Agent + RAG + Azure
          </span>

          <small>
            Synthetic MVP
          </small>
        </div>
      </nav>

      <main>
        <div className="app-topbar">
          <div>
            <small className="eyebrow">
              Operations workspace
            </small>

            <strong>
              {tab}
            </strong>
          </div>

          {selected && (
            <div className="topbar-status">
              <span>
                {selected.id}
              </span>

              <RiskBadge
                level={
                  selected.riskLevel
                }
              />
            </div>
          )}
        </div>

        {showShipmentContext && (
          <section className="shipment-context">
            <label className="picker">
              <span>Shipment</span>

              <select
                value={
                  selected.id
                }
                onChange={
                  (
                    event,
                  ) =>
                    selectShipment(
                      event.target.value,
                    )
                }
              >
                {shipments.map(
                  (
                    shipment,
                  ) => (
                    <option
                      key={
                        shipment.id
                      }
                      value={
                        shipment.id
                      }
                    >
                      {shipment.id}
                      {" · "}
                      {
                        shipment
                          .details
                          .destination
                      }
                    </option>
                  ),
                )}
              </select>
            </label>

            <div className="context-status">
              <StatusChip
                status={
                  selected
                    .investigationStatus
                }
              />

              <RiskBadge
                level={
                  selected.riskLevel
                }
              />
            </div>
          </section>
        )}

        {error && (
          <section className="load-message error-message">
            <div>
              <strong>
                Shipment data could not be loaded
              </strong>

              <p>
                {error} Check that FastAPI is running on
                port 8000 and that the Vite proxy is
                configured correctly.
              </p>
            </div>

            <button
              className="btn"
              onClick={reload}
            >
              Try again
            </button>
          </section>
        )}

        {loadFailures.length > 0 && (
          <section className="load-message warning-message">
            <div>
              <strong>
                Some demonstration shipments were unavailable
              </strong>

              <ul>
                {loadFailures.map(
                  (
                    failure,
                  ) => (
                    <li key={failure}>
                      {failure}
                    </li>
                  ),
                )}
              </ul>
            </div>
          </section>
        )}

        {loading && (
          <div className="empty">
            Loading shipment and prediction data…
          </div>
        )}

        {!loading
          && !error
          && shipments.length === 0
          && (
            <div className="empty">
              No demonstration shipments are configured.
            </div>
          )}

        {!loading
          && shipments.length > 0
          && (
            <>
              {tab === "Home" && (
                <Home
                  shipments={
                    shipments
                  }
                  onOpen={
                    openShipment
                  }
                  onInvestigate={
                    investigateShipment
                  }
                />
              )}

              {tab === "Shipments" && (
                <Shipments
                  shipments={
                    shipments
                  }
                  selectedId={
                    selected?.id
                  }
                  onSelect={
                    selectShipment
                  }
                />
              )}

              {tab === "Investigation" && (
                <Investigation
                  shipment={
                    selected
                  }
                  onUpdate={
                    updateShipment
                  }
                  onViewActions={() =>
                    setTab("Actions")
                  }
                />
              )}

              {tab === "Actions" && (
                <Actions
                  shipment={
                    selected
                  }
                  decisions={
                    decisions
                  }
                  onDecide={
                    decide
                  }
                  onViewBriefing={() =>
                    setTab("Briefings")
                  }
                />
              )}

              {tab === "Briefings" && (
                <Briefings
                  shipment={
                    selected
                  }
                />
              )}
            </>
          )}
      </main>
    </div>
  );
}
