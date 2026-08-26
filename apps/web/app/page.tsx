"use client";

import {
  ArrowDownRight,
  ArrowRight,
  ArrowUpRight,
  Activity,
  AlertTriangle,
  Bath,
  BedDouble,
  Bookmark,
  Building2,
  Bot,
  Check,
  ChevronLeft,
  ChevronRight,
  Compass,
  Database,
  ExternalLink,
  FileText,
  GraduationCap,
  Heart,
  Home,
  Hospital,
  Info,
  Layers3,
  ListFilter,
  LockKeyhole,
  Map,
  MapPin,
  Menu,
  MessageCircleMore,
  Navigation,
  PanelLeftClose,
  RotateCcw,
  Route,
  Search,
  ShieldCheck,
  Sparkles,
  SquareStack,
  Trees,
  UserRound,
  UtensilsCrossed,
  Waves,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { flushSync } from "react-dom";
import Image from "next/image";
import {
  ActionPlan,
  AgentEvent,
  api,
  Candidate,
  ClarificationTurn,
  DecisionBrief,
  Evidence,
  Listing,
  ListingSearchResult,
  MemoryContextPacket,
  Profile,
  ProfileUpdate,
  Proposal,
  RankingDelta,
} from "@/lib/api";
import ListingMap from "./listing-map";

type HousingMode = "BUY" | "RENT";

const GOALS: Record<HousingMode, string> = {
  BUY: "My family and I are moving from the U.S. to Ho Chi Minh City. Our home budget is $175,000. I work remotely. We want water nearby, healthcare within 30 minutes, and we strongly prefer buying over renting.",
  RENT: "My family and I are moving from the U.S. to Ho Chi Minh City. Our rent budget is $1,500 per month. I work remotely. We want water nearby, healthcare within 30 minutes, and we want to rent before deciding whether to buy.",
};

type Screen = "landing" | "setup" | "results" | "homes";

export default function HomePage() {
  const [screen, setScreen] = useState<Screen>("landing");
  const [mode, setMode] = useState<HousingMode>("BUY");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [profileId, setProfileId] = useState("");
  const [profile, setProfile] = useState<Profile | null>(null);
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [listings, setListings] = useState<Listing[]>([]);
  const [listingSearch, setListingSearch] =
    useState<ListingSearchResult | null>(null);
  const [listingBusy, setListingBusy] = useState(false);
  const [listingError, setListingError] = useState("");
  const [listingBand, setListingBand] = useState<"ALL" | Listing["price_band"]>(
    "ALL",
  );
  const [galleryOnly, setGalleryOnly] = useState(false);
  const [listingPage, setListingPage] = useState(1);
  const [evidence, setEvidence] = useState<Evidence | null>(null);
  const [selected, setSelected] = useState<string>("");
  const [feedbackTarget, setFeedbackTarget] = useState<string>("");
  const [rejected, setRejected] = useState<string[]>([]);
  const [proposal, setProposal] = useState<Proposal | null>(null);
  const [proposalMemory, setProposalMemory] =
    useState<MemoryContextPacket | null>(null);
  const [clarification, setClarification] = useState<ClarificationTurn | null>(
    null,
  );
  const [deltas, setDeltas] = useState<RankingDelta[]>([]);
  const [changeExplanation, setChangeExplanation] = useState("");
  const [detail, setDetail] = useState<Listing | null>(null);
  const [saved, setSaved] = useState<string[]>([]);
  const [compare, setCompare] = useState<string[]>([]);
  const [plan, setPlan] = useState<ActionPlan | null>(null);
  const [brief, setBrief] = useState<DecisionBrief | null>(null);
  const [briefOpen, setBriefOpen] = useState(false);
  const [briefBusy, setBriefBusy] = useState(false);
  const [activeBriefRunId, setActiveBriefRunId] = useState("");
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [listingDeltas, setListingDeltas] = useState<
    {
      listing_id: string;
      title: string;
      previous_rank: number;
      new_rank: number;
      previous_score: number;
      new_score: number;
    }[]
  >([]);
  const [profileOpen, setProfileOpen] = useState(true);
  const [profileEditorOpen, setProfileEditorOpen] = useState(false);
  const [mobileMap, setMobileMap] = useState(false);

  const selectedCandidate =
    candidates.find((item) => item.id === selected) ?? candidates[0];
  const priceBandListings = useMemo(
    () =>
      listingBand === "ALL"
        ? listings
        : listings.filter((item) => item.price_band === listingBand),
    [listingBand, listings],
  );
  const galleryCount = useMemo(
    () => priceBandListings.filter((item) => item.image_urls.length > 1).length,
    [priceBandListings],
  );
  const bandListings = useMemo(
    () =>
      galleryOnly
        ? priceBandListings.filter((item) => item.image_urls.length > 1)
        : priceBandListings,
    [galleryOnly, priceBandListings],
  );
  const listingPageSize = 12;
  const listingPages = Math.max(
    1,
    Math.ceil(bandListings.length / listingPageSize),
  );
  const visibleListings = bandListings.slice(
    (listingPage - 1) * listingPageSize,
    listingPage * listingPageSize,
  );

  useEffect(() => {
    let cancelled = false;
    async function restoreProfile() {
      const savedProfileId = window.localStorage.getItem(
        "roamstead_profile_id",
      );
      const savedMode = window.localStorage.getItem(
        "roamstead_housing_mode",
      ) as HousingMode | null;
      if (!savedProfileId || (savedMode !== "BUY" && savedMode !== "RENT"))
        return;
      try {
        const restoredProfile = await api.profile(savedProfileId);
        const [ranked, ruleEvidence, savedListings, savedState, priorBriefs] =
          await Promise.all([
            api.neighborhoods(savedProfileId),
            api.evidence(),
            api.listings(savedMode, savedProfileId),
            api.saved(savedProfileId),
            api.briefs(savedProfileId),
          ]);
        if (cancelled) return;
        setMode(savedMode);
        setProfileId(savedProfileId);
        setProfile(restoredProfile);
        setClarification(
          [...restoredProfile.clarifications]
            .reverse()
            .find((item) => item.status === "AWAITING_ANSWER") ?? null,
        );
        setCandidates(ranked.items);
        setSelected(ranked.items[0]?.id ?? "");
        setEvidence(ruleEvidence);
        setListings(savedListings.items);
        setListingSearch(savedListings);
        setSaved(savedState.saved);
        setBrief(priorBriefs.items[0] ?? null);
        setAgentEvents([
          {
            id: "restore-profile",
            run_id: "session",
            sequence: 1,
            event_type: "TOOL_RESULT",
            actor: "ProfileStore",
            title: "Decision memory restored",
            summary: `Profile v${restoredProfile.version}, feedback, saved homes, and prior briefs loaded from the durable database.`,
            status: "COMPLETED",
            public_payload: {},
            created_at: new Date().toISOString(),
          },
          {
            id: "restore-listings",
            run_id: "session",
            sequence: 2,
            event_type: "TOOL_RESULT",
            actor: "ListingCatalog",
            title: "Verified snapshot loaded",
            summary: `${savedListings.returned} real Batdongsan properties loaded without a new Gemini request.`,
            status: "COMPLETED",
            public_payload: {},
            created_at: new Date().toISOString(),
          },
        ]);
        setScreen("homes");
      } catch {
        window.localStorage.removeItem("roamstead_profile_id");
        window.localStorage.removeItem("roamstead_housing_mode");
      }
    }
    void restoreProfile();
    return () => {
      cancelled = true;
    };
  }, []);

  async function start() {
    setBusy(true);
    setError("");
    try {
      const created = await api.createSession(mode);
      setSessionId(created.session.id);
      setProfileId(created.session.profile_id);
      setProfile(created.profile);
      setAgentEvents([
        {
          id: "profile-start",
          run_id: created.session.id,
          sequence: 1,
          event_type: "AGENT_STATUS",
          actor: "PartnerCoordinator",
          title: "Decision Profile started",
          summary:
            "Your HCMC buy or rent goal is ready for you to review and customize.",
          status: "COMPLETED",
          public_payload: {},
          created_at: new Date().toISOString(),
        },
      ]);
      setScreen("setup");
    } catch {
      setError(
        "The Roamstead API is not reachable. Start the FastAPI service on port 8000, then try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  function changeMode(nextMode: HousingMode) {
    if (nextMode === mode) return;
    setMode(nextMode);
    setScreen("landing");
    setSessionId("");
    setProfileId("");
    setProfile(null);
    setProfileEditorOpen(false);
    setCandidates([]);
    setListings([]);
    setListingSearch(null);
    setListingBusy(false);
    setListingError("");
    setListingBand("ALL");
    setGalleryOnly(false);
    setListingPage(1);
    setSelected("");
    setFeedbackTarget("");
    setRejected([]);
    setProposal(null);
    setClarification(null);
    setDeltas([]);
    setChangeExplanation("");
    setDetail(null);
    setSaved([]);
    setCompare([]);
    setPlan(null);
    setBrief(null);
    setBriefOpen(false);
    setAgentEvents([]);
    setListingDeltas([]);
    setError("");
    window.localStorage.removeItem("roamstead_profile_id");
    window.localStorage.removeItem("roamstead_housing_mode");
  }

  async function saveProfile(update: ProfileUpdate, onboarding = false) {
    setBusy(true);
    setError("");
    try {
      const result = await api.updateProfile(profileId, update);
      setProfile(result.profile);
      setCandidates(result.recommendations);
      setDeltas(result.deltas);
      const focus = result.recommendations[0]?.id ?? "";
      setSelected(focus);
      setEvidence(await api.evidence());
      window.localStorage.setItem("roamstead_profile_id", profileId);
      window.localStorage.setItem("roamstead_housing_mode", mode);
      setProfileEditorOpen(false);
      setDetail(null);
      setScreen("homes");
      await searchLiveListings(false, focus, profileId, mode);
      const clarificationResult = await api.clarification(profileId);
      setClarification(clarificationResult.question ?? null);
      setAgentEvents([
        {
          id: "profile-write",
          run_id: sessionId || "profile",
          sequence: 1,
          event_type: "TOOL_RESULT",
          actor: "ProfileStore",
          title: "Decision Profile saved",
          summary: `Profile v${result.profile.version} was written to the local database with revision history.`,
          status: "COMPLETED",
          public_payload: {},
          created_at: new Date().toISOString(),
        },
        {
          id: "fit-score",
          run_id: sessionId || "profile",
          sequence: 2,
          event_type: "TOOL_RESULT",
          actor: "FitScoreTool",
          title: "Eligible matches scored",
          summary:
            "Only listings meeting your property type, budget, bedroom, and bathroom requirements are ranked. Gemini does not calculate the numeric Fit Score.",
          status: "COMPLETED",
          public_payload: {},
          created_at: new Date().toISOString(),
        },
        ...clarificationResult.events,
      ]);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "Your profile changes could not be saved.",
      );
      if (!onboarding) setProfileEditorOpen(true);
    } finally {
      setBusy(false);
    }
  }

  async function searchLiveListings(
    refresh = false,
    focusedNeighborhoodId = selected,
    activeProfileId = profileId,
    activeMode = mode,
  ) {
    setListingBusy(true);
    setListingError("");
    try {
      const result = await api.listings(
        activeMode,
        activeProfileId,
        focusedNeighborhoodId || undefined,
        refresh,
      );
      setListings(result.items);
      setListingSearch(result);
      setListingPage(1);
      setListingBand("ALL");
      setGalleryOnly(false);
    } catch (caught) {
      setListings([]);
      setListingSearch(null);
      setListingError(
        caught instanceof Error
          ? caught.message
          : "The weekly listing catalog is unavailable.",
      );
    } finally {
      setListingBusy(false);
    }
  }

  async function leaveFeedback(
    item: Candidate | Listing,
    reason: string,
    note?: string,
  ) {
    if (!profileId) return;
    setBusy(true);
    try {
      const result = await api.feedback(profileId, {
        target_id: item.id,
        action: "REJECT",
        reason,
        note: note?.trim() || undefined,
      });
      setProfile(result.profile);
      setRejected((items) => Array.from(new Set([...items, item.id])));
      setFeedbackTarget("");
      if (result.proposal) {
        setProposal(result.proposal);
        setProposalMemory(result.memory_context ?? null);
      }
    } finally {
      setBusy(false);
    }
  }

  async function decide(decision: "ACCEPT" | "SOFTEN" | "REJECT") {
    if (!proposal) return;
    setBusy(true);
    try {
      const before = new globalThis.Map(
        listings.map((item, index) => [
          item.id,
          { rank: index + 1, score: item.fit_score, title: item.title },
        ]),
      );
      const result = await api.decide(profileId, proposal.id, decision);
      setProfile(result.profile);
      setCandidates(result.recommendations);
      setDeltas(result.deltas);
      setChangeExplanation(result.explanation);
      setProposal(null);
      setProposalMemory(null);
      if (decision !== "REJECT") {
        const refreshed = await api.listings(mode, profileId);
        setListings(refreshed.items);
        setListingSearch(refreshed);
        setListingDeltas(
          refreshed.items
            .map((item, index) => {
              const previous = before.get(item.id);
              return previous
                ? {
                    listing_id: item.id,
                    title: item.title,
                    previous_rank: previous.rank,
                    new_rank: index + 1,
                    previous_score: previous.score,
                    new_score: item.fit_score,
                  }
                : null;
            })
            .filter((item): item is NonNullable<typeof item> =>
              Boolean(
                item &&
                (item.previous_rank !== item.new_rank ||
                  item.previous_score !== item.new_score),
              ),
            )
            .slice(0, 8),
        );
        setListingPage(1);
      }
    } finally {
      setBusy(false);
    }
  }

  async function answerAdaptiveClarification(optionId: string) {
    if (!clarification || !profileId) return;
    setBusy(true);
    try {
      const result = await api.answerClarification(
        profileId,
        clarification.id,
        optionId,
      );
      setProfile(result.profile);
      setClarification(null);
      setAgentEvents(result.events);
      if (result.proposal) setProposal(result.proposal);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The clarification answer could not be saved.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function undo() {
    const result = await api.undo(profileId);
    setProfile(result.profile);
    setCandidates(result.recommendations);
    setDeltas([]);
    setChangeExplanation("");
    setSelected(result.recommendations[0].id);
  }

  async function saveItem(id: string) {
    await api.save(profileId, id);
    setSaved((items) => Array.from(new Set([...items, id])));
  }

  async function buildPlan() {
    setBusy(true);
    try {
      setPlan(await api.plan(profileId));
    } finally {
      setBusy(false);
    }
  }

  async function buildDecisionBrief() {
    if (compare.length !== 3 || !profileId) return;
    setBriefBusy(true);
    setError("");
    try {
      const result = await api.createBrief(profileId, compare);
      flushSync(() => setActiveBriefRunId(result.run.id));
      await api.streamBriefEvents(result.run.id, (event) => {
        flushSync(() =>
          setAgentEvents((current) =>
            current.some((item) => item.id === event.id)
              ? current
              : [...current, event],
          ),
        );
      });
      const completedBrief = result.brief ?? (await api.brief(result.run.id));
      setBrief(completedBrief);
      setBriefOpen(true);
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The Decision Brief could not be created.",
      );
    } finally {
      setActiveBriefRunId("");
      setBriefBusy(false);
    }
  }

  async function openSavedBrief() {
    if (!brief) return;
    setBriefOpen(true);
    if (agentEvents.some((event) => event.run_id === brief.run_id)) return;
    try {
      await api.streamBriefEvents(brief.run_id, (event) => {
        flushSync(() =>
          setAgentEvents((current) =>
            current.some((item) => item.id === event.id)
              ? current
              : [...current, event],
          ),
        );
      });
    } catch (caught) {
      setError(
        caught instanceof Error
          ? caught.message
          : "The saved agent trace could not be restored.",
      );
    }
  }

  return (
    <main className="app-shell">
      <Header
        mode={mode}
        onMode={changeMode}
        savedCount={saved.length}
        profileOpen={profileOpen}
        onProfile={() => setProfileOpen((open) => !open)}
        onPlan={buildPlan}
        canPlan={screen === "homes"}
      />
      <div className="workspace">
        <SideNav
          screen={screen}
          onExplore={() => setScreen(candidates.length ? "homes" : "landing")}
        />
        {profileOpen && screen === "homes" && (
          <DecisionProfile
            profile={profile}
            onClose={() => setProfileOpen(false)}
            onEdit={() => setProfileEditorOpen(true)}
            onUndo={undo}
            hasRevision={Boolean(deltas.length)}
          />
        )}
        <section
          className={`content-panel ${screen === "setup" ? "properties-wide" : ""} ${screen === "homes" ? "listing-results-panel" : ""} ${mobileMap ? "mobile-hidden" : ""}`}
        >
          {screen === "landing" && (
            <Landing
              mode={mode}
              busy={busy}
              error={error}
              onStart={start}
              onMode={changeMode}
            />
          )}
          {screen === "setup" && profile && (
            <ProfileSetup
              mode={mode}
              profile={profile}
              busy={busy}
              error={error}
              onboarding
              onSave={(update) => saveProfile(update, true)}
              onClose={() => setScreen("landing")}
            />
          )}
          {screen === "homes" && (
            <Discovery
              mode={mode}
              profile={profile}
              onMode={changeMode}
              screen={screen}
              candidates={candidates}
              selected={selected}
              rejected={rejected}
              listings={visibleListings}
              listingTotal={bandListings.length}
              listingSearch={listingSearch}
              listingBusy={listingBusy}
              listingError={listingError}
              listingBand={listingBand}
              galleryOnly={galleryOnly}
              galleryCount={galleryCount}
              listingPage={listingPage}
              listingPages={listingPages}
              feedbackTarget={feedbackTarget}
              saved={saved}
              compare={compare}
              deltas={deltas}
              listingDeltas={listingDeltas}
              explanation={changeExplanation}
              agentEvents={agentEvents}
              priorBrief={brief}
              onSelect={setSelected}
              onFeedback={setFeedbackTarget}
              onReason={leaveFeedback}
              onHomes={(id) => {
                setSelected(id);
                void searchLiveListings(false, id);
              }}
              onNeighborhoods={() => undefined}
              onRefresh={() => void searchLiveListings(true)}
              onBand={(band) => {
                setListingBand(band);
                setGalleryOnly(false);
                setListingPage(1);
              }}
              onGallery={() => {
                setGalleryOnly((active) => !active);
                setListingPage(1);
              }}
              onPage={setListingPage}
              onDetail={setDetail}
              onSave={saveItem}
              onCompare={(id) =>
                setCompare((items) =>
                  items.includes(id)
                    ? items.filter((item) => item !== id)
                    : [...items, id].slice(-3),
                )
              }
              onEditProfile={() => setProfileEditorOpen(true)}
              onOpenBrief={openSavedBrief}
            />
          )}
        </section>
        {screen !== "homes" && screen !== "setup" && (
          <MapPanel
            landing
            candidates={candidates}
            selected={selectedCandidate?.id}
            onSelect={setSelected}
            mobileMap={mobileMap}
          />
        )}
        {screen === "homes" && (
          <ListingMap
            listings={bandListings}
            mobile={mobileMap}
            onListing={setDetail}
          />
        )}
      </div>

      {screen === "homes" && (
        <button
          className="map-toggle"
          onClick={() => setMobileMap((shown) => !shown)}
        >
          {mobileMap ? (
            <>
              <ListFilter size={16} /> List
            </>
          ) : (
            <>
              <Map size={16} /> Map
            </>
          )}
        </button>
      )}

      {clarification && !proposal && (
        <ClarificationPrompt
          clarification={clarification}
          busy={busy}
          onAnswer={answerAdaptiveClarification}
        />
      )}
      {proposal && (
        <PreferencePrompt
          proposal={proposal}
          memory={proposalMemory}
          busy={busy}
          onDecision={decide}
        />
      )}
      {profileEditorOpen && profile && (
        <div className="modal-backdrop profile-editor-backdrop">
          <ProfileSetup
            mode={mode}
            profile={profile}
            busy={busy}
            error={error}
            onSave={(update) => saveProfile(update)}
            onClose={() => setProfileEditorOpen(false)}
          />
        </div>
      )}
      {detail && evidence && (
        <PropertyDetail
          mode={mode}
          listing={detail}
          evidence={evidence}
          saved={saved.includes(detail.id)}
          comparing={compare.includes(detail.id)}
          onClose={() => setDetail(null)}
          onSave={() => saveItem(detail.id)}
          onCompare={() =>
            setCompare((items) =>
              items.includes(detail.id)
                ? items.filter((id) => id !== detail.id)
                : [...items, detail.id].slice(-3),
            )
          }
        />
      )}
      {plan && <MovePlan plan={plan} onClose={() => setPlan(null)} />}
      {brief && briefOpen && (
        <DecisionBriefModal
          brief={brief}
          events={agentEvents.filter((event) => event.run_id === brief.run_id)}
          onClose={() => setBriefOpen(false)}
        />
      )}
      {briefBusy && (
        <DecisionBriefBuildModal
          runId={activeBriefRunId}
          events={
            activeBriefRunId
              ? agentEvents.filter((event) => event.run_id === activeBriefRunId)
              : []
          }
        />
      )}
      {compare.length > 0 && (
        <div className="compare-tray">
          <div>
            <SquareStack size={18} />
            <span>{compare.length}/3 properties selected</span>
          </div>
          {compare.length === 3 && (
            <button
              className="brief-tray-cta"
              onClick={buildDecisionBrief}
              disabled={briefBusy}
            >
              {briefBusy ? "Agents working…" : "Build Decision Brief"}
              <FileText size={15} />
            </button>
          )}
          <button onClick={() => setCompare([])}>Clear</button>
        </div>
      )}
    </main>
  );
}

function Header({
  mode,
  savedCount,
  profileOpen,
  onMode,
  onProfile,
  onPlan,
  canPlan,
}: {
  mode: HousingMode;
  savedCount: number;
  profileOpen: boolean;
  onMode: (mode: HousingMode) => void;
  onProfile: () => void;
  onPlan: () => void;
  canPlan: boolean;
}) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-mark">
          <Navigation size={17} fill="currentColor" />
        </span>
        <span>Roamstead</span>
      </div>
      <nav className="topnav" aria-label="Housing mode">
        <button
          className={mode === "BUY" ? "active" : ""}
          onClick={() => onMode("BUY")}
        >
          Buy
        </button>
        <button
          className={mode === "RENT" ? "active" : ""}
          onClick={() => onMode("RENT")}
        >
          Rent
        </button>
        <button>Explore</button>
      </nav>
      <div className="location-pill">
        <MapPin size={16} />
        <span>Ho Chi Minh City, Vietnam</span>
        <span className="scope-dot">MVP</span>
      </div>
      <div className="header-actions">
        <button className="icon-label">
          <Heart size={18} />
          <span>Saved</span>
          {savedCount > 0 && <b>{savedCount}</b>}
        </button>
        <button
          className={`icon-label ${profileOpen ? "selected" : ""}`}
          onClick={onProfile}
        >
          <UserRound size={18} />
          <span>Decision profile</span>
        </button>
        {canPlan && (
          <button className="primary compact" onClick={onPlan}>
            <Sparkles size={16} /> Build move plan
          </button>
        )}
      </div>
    </header>
  );
}

function SideNav({
  screen,
  onExplore,
}: {
  screen: Screen;
  onExplore: () => void;
}) {
  return (
    <aside className="side-nav">
      <button aria-label="Menu">
        <Menu />
      </button>
      <div className="side-nav-main">
        <button aria-label="Home">
          <Home />
        </button>
        <button
          className={screen !== "landing" ? "active" : ""}
          aria-label="Explore"
          onClick={onExplore}
        >
          <Compass />
        </button>
        <button aria-label="Partner chat">
          <MessageCircleMore />
        </button>
        <button aria-label="Saved">
          <Bookmark />
        </button>
      </div>
      <button aria-label="Account">
        <span className="avatar">KL</span>
      </button>
    </aside>
  );
}

function Landing({
  mode,
  busy,
  error,
  onStart,
  onMode,
}: {
  mode: HousingMode;
  busy: boolean;
  error: string;
  onStart: () => void;
  onMode: (mode: HousingMode) => void;
}) {
  return (
    <div className="landing">
      <div className="eyebrow">
        <Sparkles size={15} /> Your collaborative housing partner
      </div>
      <h1>
        Where in HCMC
        <br />
        fits your <em>life?</em>
      </h1>
      <p className="landing-copy">
        Start with the life you want. Roamstead will surface the tradeoffs,
        learn from your feedback, and keep you in control.
      </p>
      <div
        className="landing-mode"
        role="group"
        aria-label="Choose buy or rent"
      >
        <button
          className={mode === "BUY" ? "active" : ""}
          onClick={() => onMode("BUY")}
        >
          <Building2 size={15} /> Buy a home
        </button>
        <button
          className={mode === "RENT" ? "active" : ""}
          onClick={() => onMode("RENT")}
        >
          <Home size={15} /> Rent first
        </button>
      </div>
      <div className="goal-box">
        <div className="goal-box-top">
          <MessageCircleMore size={18} />
          <span>Tell Roamstead what you’re looking for</span>
          <span className="preset">Demo goal</span>
        </div>
        <p>{GOALS[mode]}</p>
        <button
          className="primary start-button"
          onClick={onStart}
          disabled={busy}
        >
          {busy ? "Creating your profile…" : "Set up my profile"}
          <ArrowRight size={18} />
        </button>
      </div>
      {error && (
        <div className="error-banner">
          <Info size={17} />
          {error}
        </div>
      )}
      <div className="trust-row">
        <span>
          <ShieldCheck size={16} /> You approve preference changes
        </span>
        <span>
          <Layers3 size={16} /> Explainable ranking
        </span>
        <span>
          <LockKeyhole size={16} /> Source-backed guidance
        </span>
      </div>
      <div className="hcmc-note">
        <span className="mini-map-pin">
          <MapPin size={16} />
        </span>
        <div>
          <b>Focused for this MVP</b>
          <p>Verified properties in Ho Chi Minh City. More cities come next.</p>
        </div>
      </div>
    </div>
  );
}

const PRIORITY_FIELDS = [
  {
    key: "budget",
    label: "Stay within budget",
    hint: "Favor homes with comfortable price headroom",
  },
  {
    key: "space",
    label: "Bedrooms & bathrooms",
    hint: "Match your minimum room targets",
  },
  {
    key: "healthcare",
    label: "Healthcare access",
    hint: "Favor convenient access to major hospitals",
  },
  {
    key: "remote_work",
    label: "Remote-work readiness",
    hint: "Favor reliable infrastructure and connectivity",
  },
  {
    key: "waterfront",
    label: "Waterfront access",
    hint: "Favor river, canal, and green-water access",
  },
  {
    key: "quiet",
    label: "Quiet surroundings",
    hint: "Favor calmer, lower-density locations",
  },
  {
    key: "international_school",
    label: "International-school access",
    hint: "Favor districts with stronger access to international schools",
  },
  {
    key: "food_access",
    label: "Food & daily needs",
    hint: "Favor convenient groceries, markets, dining, and essentials",
  },
] as const;

function constraintValue(profile: Profile, key: string, fallback: number) {
  const value = profile.hard_constraints.find(
    (item) => item.key === key,
  )?.value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function priorityValue(profile: Profile, key: string, fallback: number) {
  return (
    profile.preferences.find((item) => item.key === key)?.weight ?? fallback
  );
}

function priorityLabel(value: number) {
  if (value >= 0.85) return "Must have";
  if (value >= 0.65) return "Important";
  if (value >= 0.4) return "Nice to have";
  return "Flexible";
}

function ProfileSetup({
  mode,
  profile,
  busy,
  error,
  onboarding = false,
  onSave,
  onClose,
}: {
  mode: HousingMode;
  profile: Profile;
  busy: boolean;
  error: string;
  onboarding?: boolean;
  onSave: (update: ProfileUpdate) => void;
  onClose: () => void;
}) {
  const propertyOptions: ProfileUpdate["property_types"] = [
    "Apartment",
    "House",
  ];
  const rawTypes = String(
    profile.hard_constraints.find((item) => item.key === "property_types")
      ?.value ?? "Apartment,House",
  ).toLowerCase();
  const storedTypes: ProfileUpdate["property_types"] = [];
  if (/apartment|condo|studio|flat/.test(rawTypes))
    storedTypes.push("Apartment");
  if (
    /house|townhouse|town house|villa|shophouse|shop house|home/.test(rawTypes)
  )
    storedTypes.push("House");
  if (!storedTypes.length) storedTypes.push("Apartment", "House");
  const [form, setForm] = useState<ProfileUpdate>({
    budget_usd: constraintValue(
      profile,
      mode === "RENT" ? "rent_budget" : "budget",
      mode === "RENT" ? 1500 : 175000,
    ),
    min_beds: constraintValue(profile, "min_beds", 1),
    min_baths: constraintValue(profile, "min_baths", 1),
    max_international_school_minutes: constraintValue(
      profile,
      "max_international_school_minutes",
      30,
    ),
    max_food_minutes: constraintValue(profile, "max_food_minutes", 15),
    property_types: storedTypes,
    priorities: Object.fromEntries(
      PRIORITY_FIELDS.map((item) => [
        item.key,
        priorityValue(profile, item.key, 0.5),
      ]),
    ),
  });

  function togglePropertyType(
    propertyType: ProfileUpdate["property_types"][number],
  ) {
    setForm((current) => ({
      ...current,
      property_types: current.property_types.includes(propertyType)
        ? current.property_types.filter((item) => item !== propertyType)
        : [...current.property_types, propertyType],
    }));
  }

  return (
    <section
      className={`profile-setup ${onboarding ? "onboarding" : "editor"}`}
    >
      <div className="profile-setup-heading">
        <div>
          <span className="eyebrow plain">
            {onboarding
              ? "Your matching profile"
              : `Profile v${profile.version}`}
          </span>
          <h2>
            {onboarding
              ? "What does the right home look like?"
              : "Edit your preferences"}
          </h2>
          <p>
            Every Fit Score is recalculated from these choices. You can change
            them whenever your plans change.
          </p>
        </div>
        <button
          className="modal-close static"
          onClick={onClose}
          aria-label={onboarding ? "Back" : "Close profile editor"}
        >
          {onboarding ? <ChevronLeft size={20} /> : <X size={20} />}
        </button>
      </div>

      <div className="profile-form-section">
        <div className="profile-form-title">
          <span>1</span>
          <div>
            <h3>Your search criteria</h3>
            <p>These define the practical shape of your search.</p>
          </div>
        </div>
        <div className="profile-number-grid">
          <label>
            <span>
              {mode === "RENT"
                ? "Monthly budget (USD)"
                : "Purchase budget (USD)"}
            </span>
            <div className="number-input">
              <b>$</b>
              <input
                type="number"
                min={100}
                step={mode === "RENT" ? 100 : 5000}
                value={form.budget_usd}
                onChange={(event) =>
                  setForm({ ...form, budget_usd: Number(event.target.value) })
                }
              />
            </div>
          </label>
          <label>
            <span>Minimum bedrooms</span>
            <input
              type="number"
              min={0}
              max={20}
              value={form.min_beds}
              onChange={(event) =>
                setForm({ ...form, min_beds: Number(event.target.value) })
              }
            />
          </label>
          <label>
            <span>Minimum bathrooms</span>
            <input
              type="number"
              min={0}
              max={20}
              value={form.min_baths}
              onChange={(event) =>
                setForm({ ...form, min_baths: Number(event.target.value) })
              }
            />
          </label>
          <label>
            <span>International school (max min)</span>
            <input
              type="number"
              min={5}
              max={120}
              step={5}
              value={form.max_international_school_minutes}
              onChange={(event) =>
                setForm({
                  ...form,
                  max_international_school_minutes: Number(event.target.value),
                })
              }
            />
          </label>
          <label>
            <span>Food & daily needs (max min)</span>
            <input
              type="number"
              min={5}
              max={60}
              step={5}
              value={form.max_food_minutes}
              onChange={(event) =>
                setForm({
                  ...form,
                  max_food_minutes: Number(event.target.value),
                })
              }
            />
          </label>
        </div>
        <div className="property-type-field">
          <span>Property types</span>
          <div>
            {propertyOptions.map((propertyType) => (
              <button
                type="button"
                key={propertyType}
                className={
                  form.property_types.includes(propertyType) ? "selected" : ""
                }
                onClick={() => togglePropertyType(propertyType)}
              >
                {form.property_types.includes(propertyType) && (
                  <Check size={13} />
                )}
                {propertyType}
              </button>
            ))}
          </div>
        </div>
      </div>

      <div className="profile-form-section priorities-section">
        <div className="profile-form-title">
          <span>2</span>
          <div>
            <h3>What matters most?</h3>
            <p>Your importance settings become the weights behind Fit Score.</p>
          </div>
        </div>
        <div className="priority-list">
          {PRIORITY_FIELDS.map((item) => {
            const value = form.priorities[item.key] ?? 0.5;
            return (
              <label key={item.key}>
                <div>
                  <span>
                    {item.label}
                    <small>{item.hint}</small>
                  </span>
                  <b>{priorityLabel(value)}</b>
                </div>
                <input
                  type="range"
                  min="0.1"
                  max="1"
                  step="0.05"
                  value={value}
                  onChange={(event) =>
                    setForm({
                      ...form,
                      priorities: {
                        ...form.priorities,
                        [item.key]: Number(event.target.value),
                      },
                    })
                  }
                />
                <div className="priority-scale">
                  <span>Flexible</span>
                  <span>Must have</span>
                </div>
              </label>
            );
          })}
        </div>
      </div>

      {error && (
        <div className="error-banner">
          <Info size={17} />
          {error}
        </div>
      )}
      <div className="profile-setup-actions">
        <div>
          <ShieldCheck size={17} />
          <span>
            Your profile is saved locally and Gemini does not calculate Fit
            Score.
          </span>
        </div>
        <button
          className="primary"
          disabled={busy || !form.property_types.length}
          onClick={() => onSave(form)}
        >
          {busy
            ? "Saving profile…"
            : onboarding
              ? "Show my matches"
              : "Save and recalculate"}
          <ArrowRight size={17} />
        </button>
      </div>
    </section>
  );
}

function DecisionProfile({
  profile,
  onClose,
  onEdit,
  onUndo,
  hasRevision,
}: {
  profile: Profile | null;
  onClose: () => void;
  onEdit: () => void;
  onUndo: () => void;
  hasRevision: boolean;
}) {
  return (
    <aside className="profile-panel">
      <div className="profile-heading">
        <div>
          <span className="eyebrow plain">Decision memory</span>
          <h3>Your profile</h3>
        </div>
        <button onClick={onClose} aria-label="Close profile">
          <PanelLeftClose size={19} />
        </button>
      </div>
      {!profile ? (
        <div className="profile-skeleton">
          <span />
          <span />
          <span />
        </div>
      ) : (
        <>
          <div className="profile-section">
            <div className="section-label">
              <LockKeyhole size={13} /> Hard constraints
            </div>
            {profile.hard_constraints.map((item) => (
              <div className="constraint" key={item.key}>
                <Check size={13} />
                <span>{item.label}</span>
                <LockKeyhole size={12} />
              </div>
            ))}
          </div>
          <div className="profile-section">
            <div className="section-label">
              <Sparkles size={13} /> Confirmed priorities
            </div>
            {profile.preferences
              .filter((item) => item.weight >= 0.1)
              .map((item) => (
                <div className="preference" key={item.key}>
                  <div>
                    <span>{item.label}</span>
                    <small>{Math.round(item.weight * 100)} weight</small>
                  </div>
                  <div className="weight">
                    <span
                      style={{ width: `${Math.max(12, item.weight * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
          </div>
          <button className="primary full profile-edit" onClick={onEdit}>
            <ListFilter size={15} /> Edit preferences
          </button>
          {hasRevision && (
            <button className="secondary full" onClick={onUndo}>
              <RotateCcw size={15} /> Undo learned preference
            </button>
          )}
        </>
      )}
    </aside>
  );
}

function formatUsd(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}

function formatBand(band: "ALL" | Listing["price_band"]) {
  return band === "ULTRA_HIGH"
    ? "Ultra high"
    : band.charAt(0) + band.slice(1).toLowerCase();
}

const FIT_FACTOR_LABELS: Record<string, string> = {
  budget: "Budget",
  space: "Bedrooms & bathrooms",
  healthcare: "Healthcare",
  remote_work: "Remote work",
  waterfront: "Waterfront",
  quiet: "Quiet",
  international_school: "International school",
  food_access: "Food & daily needs",
};

function Discovery(props: {
  mode: HousingMode;
  onMode: (mode: HousingMode) => void;
  profile: Profile | null;
  screen: Screen;
  candidates: Candidate[];
  selected: string;
  rejected: string[];
  listings: Listing[];
  listingTotal: number;
  listingSearch: ListingSearchResult | null;
  listingBusy: boolean;
  listingError: string;
  listingBand: "ALL" | Listing["price_band"];
  galleryOnly: boolean;
  galleryCount: number;
  listingPage: number;
  listingPages: number;
  feedbackTarget: string;
  saved: string[];
  compare: string[];
  deltas: RankingDelta[];
  listingDeltas: {
    listing_id: string;
    title: string;
    previous_rank: number;
    new_rank: number;
    previous_score: number;
    new_score: number;
  }[];
  explanation: string;
  agentEvents: AgentEvent[];
  priorBrief: DecisionBrief | null;
  onSelect: (id: string) => void;
  onFeedback: (id: string) => void;
  onReason: (item: Candidate | Listing, reason: string, note?: string) => void;
  onHomes: (id: string) => void;
  onNeighborhoods: () => void;
  onRefresh: () => void;
  onBand: (band: "ALL" | Listing["price_band"]) => void;
  onGallery: () => void;
  onPage: (page: number) => void;
  onDetail: (item: Listing) => void;
  onSave: (id: string) => void;
  onCompare: (id: string) => void;
  onEditProfile: () => void;
  onOpenBrief: () => void;
}) {
  const {
    mode,
    profile,
    screen,
    candidates,
    selected,
    rejected,
    listings,
    listingTotal,
    listingSearch,
    listingBusy,
    listingError,
    listingBand,
    galleryOnly,
    galleryCount,
    listingPage,
    listingPages,
    feedbackTarget,
    saved,
    compare,
    deltas,
    listingDeltas,
    explanation,
    agentEvents,
    priorBrief,
  } = props;
  const budget = profile?.hard_constraints.find(
    (item) => item.key === (mode === "RENT" ? "rent_budget" : "budget"),
  );
  const beds = profile?.hard_constraints.find(
    (item) => item.key === "min_beds",
  );
  const baths = profile?.hard_constraints.find(
    (item) => item.key === "min_baths",
  );
  const [feedbackReason, setFeedbackReason] = useState("");
  const [feedbackNote, setFeedbackNote] = useState("");
  const selectFeedbackTarget = (id: string) => {
    setFeedbackReason("");
    setFeedbackNote("");
    props.onFeedback(id);
  };
  return (
    <div className="discovery">
      <div className="discovery-toolbar">
        <div>
          <span className="eyebrow plain">Ho Chi Minh City</span>
          <h2>Properties matched to your profile</h2>
        </div>
      </div>
      <div className="filter-row">
        <div className="mode-filter">
          <button
            className={mode === "BUY" ? "selected" : ""}
            onClick={() => props.onMode("BUY")}
          >
            <Building2 size={15} /> Buy
          </button>
          <button
            className={mode === "RENT" ? "selected" : ""}
            onClick={() => props.onMode("RENT")}
          >
            <Home size={15} /> Rent
          </button>
        </div>
        {budget && (
          <button>
            {formatUsd(Number(budget.value))}
            {mode === "RENT" ? "/mo" : " max"}
          </button>
        )}
        {beds && (
          <button>
            <BedDouble size={15} /> {beds.value}+ beds
          </button>
        )}
        {baths && (
          <button>
            <Bath size={15} /> {baths.value}+ baths
          </button>
        )}
        <button onClick={props.onEditProfile}>
          <ListFilter size={15} /> Edit profile
        </button>
      </div>
      {explanation && (
        <WhyChanged listingDeltas={listingDeltas} explanation={explanation} />
      )}
      {screen === "results" ? (
        <>
          <div className="result-summary">
            <p>
              <b>{candidates.length} neighborhoods</b> match your hard
              constraints
            </p>
            <span>
              Ranked from your profile <Info size={13} />
            </span>
          </div>
          <div className="candidate-list">
            {candidates.map((item) => {
              const delta = deltas.find(
                (entry) => entry.candidate_id === item.id,
              );
              const isRejected = rejected.includes(item.id);
              return (
                <article
                  key={item.id}
                  className={`candidate-card ${selected === item.id ? "selected" : ""} ${isRejected ? "rejected" : ""}`}
                  onClick={() => props.onSelect(item.id)}
                >
                  <div
                    className="candidate-photo"
                    style={{ backgroundImage: `url(${item.image})` }}
                  >
                    <span className="rank">#{item.rank}</span>
                    <button className="heart" aria-label="Save">
                      <Heart size={17} />
                    </button>
                    {delta && delta.previous_rank !== delta.new_rank && (
                      <span
                        className={`rank-delta ${delta.new_rank < delta.previous_rank ? "up" : "down"}`}
                      >
                        {delta.new_rank < delta.previous_rank ? (
                          <ArrowUpRight size={13} />
                        ) : (
                          <ArrowDownRight size={13} />
                        )}{" "}
                        from #{delta.previous_rank}
                      </span>
                    )}
                  </div>
                  <div className="candidate-body">
                    <div className="candidate-title">
                      <div>
                        <h3>{item.name}</h3>
                        <span>{item.district}</span>
                      </div>
                      <div className="score">
                        <b>{item.score}</b>
                        <small>fit</small>
                      </div>
                    </div>
                    <p className="tagline">{item.tagline}</p>
                    <div className="metric-row">
                      <span>
                        <Building2 size={14} />{" "}
                        {mode === "BUY"
                          ? `from $${Math.round(item.price_from_usd / 1000)}k`
                          : `from $${item.rent_from_usd.toLocaleString()}/mo`}
                      </span>
                      <span>
                        <Hospital size={14} /> {item.hospital_minutes} min
                      </span>
                      <span>
                        <Waves size={14} /> {item.waterfront_minutes} min
                      </span>
                    </div>
                    <div className="tradeoff">
                      <Info size={14} />
                      <span>{item.tradeoff}</span>
                    </div>
                    {isRejected ? (
                      <div className="rejected-label">
                        <Check size={15} /> Feedback saved: too urban
                      </div>
                    ) : feedbackTarget === item.id ? (
                      <div
                        className="reason-picker"
                        onClick={(event) => event.stopPropagation()}
                      >
                        <span>What doesn’t fit?</span>
                        <button
                          onClick={() => props.onReason(item, "TOO_URBAN")}
                        >
                          Too urban
                        </button>
                        <button
                          onClick={() => props.onReason(item, "TOO_EXPENSIVE")}
                        >
                          Too expensive
                        </button>
                        <button
                          onClick={() => props.onReason(item, "HEALTHCARE")}
                        >
                          Healthcare
                        </button>
                        <button
                          className="close-reasons"
                          onClick={() => selectFeedbackTarget("")}
                        >
                          <X size={14} />
                        </button>
                      </div>
                    ) : (
                      <div className="card-actions">
                        <button
                          className="text-button"
                          onClick={(event) => {
                            event.stopPropagation();
                            selectFeedbackTarget(item.id);
                          }}
                        >
                          Not for me
                        </button>
                        <button
                          className="secondary small"
                          onClick={(event) => {
                            event.stopPropagation();
                            props.onHomes(item.id);
                          }}
                        >
                          Search live homes <ArrowRight size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </>
      ) : (
        <>
          <AgentActivity
            events={agentEvents}
            priorBrief={priorBrief}
            onOpenBrief={props.onOpenBrief}
          />
          <div className="live-source-bar">
            <div>
              <Sparkles size={17} />
              <span>
                <b>Gemini weekly listing catalog</b>
                <small>
                  Every published property includes a validated local photo · no
                  synthetic fallback
                </small>
              </span>
            </div>
            {listingSearch && (
              <button
                className="text-button"
                onClick={props.onRefresh}
                disabled={listingBusy}
              >
                <RotateCcw size={14} /> Check saved catalog
              </button>
            )}
          </div>
          {listingBusy && (
            <div className="live-search-state">
              <span className="search-spinner">
                <Search size={20} />
              </span>
              <h3>Calculating matches from your saved profile</h3>
              <p>
                Properties load from the local database; this does not make a
                new Gemini request.
              </p>
            </div>
          )}
          {!listingBusy && listingError && (
            <div className="live-search-state error">
              <Info size={23} />
              <h3>Listing catalog is not available</h3>
              <p>{listingError}</p>
              <button className="primary compact" onClick={props.onRefresh}>
                Check catalog again
              </button>
            </div>
          )}
          {!listingBusy && !listingError && listingSearch && (
            <>
              <div
                className="price-band-row"
                role="group"
                aria-label="Listing filters"
              >
                <span>Price range</span>
                {(["ALL", "LOW", "MEDIUM", "HIGH", "ULTRA_HIGH"] as const).map(
                  (band) => (
                    <button
                      key={band}
                      className={listingBand === band ? "active" : ""}
                      onClick={() => props.onBand(band)}
                    >
                      {formatBand(band)}
                    </button>
                  ),
                )}
                <button
                  className={`gallery-filter ${galleryOnly ? "active" : ""}`}
                  onClick={props.onGallery}
                  disabled={!galleryCount}
                >
                  <Layers3 size={13} /> Galleries ({galleryCount})
                </button>
              </div>
              <div className="result-summary">
                <p>
                  <b>
                    {listingTotal} matching listing
                    {listingTotal === 1 ? "" : "s"}
                  </b>
                  {listingSearch.pending_gallery_verification > 0 && (
                    <small>
                      {" "}
                      · {
                        listingSearch.pending_gallery_verification
                      } pending {listingSearch.minimum_photos_per_listing}-photo
                      verification
                    </small>
                  )}
                </p>
                <span>
                  Updated{" "}
                  {new Date(listingSearch.searched_at).toLocaleString([], {
                    month: "short",
                    day: "numeric",
                    hour: "2-digit",
                    minute: "2-digit",
                  })}
                </span>
              </div>
              {listings.length ? (
                <div className="listing-grid">
                  {listings.map((item) => (
                    <article
                      className={`listing-card ${rejected.includes(item.id) ? "rejected" : ""}`}
                      key={item.id}
                    >
                      <div
                        className="listing-photo sourced-photo"
                        style={{ backgroundImage: `url(${item.image_url})` }}
                      >
                        <span className="live-badge">
                          <span /> Sourced property photo
                        </span>
                        <span className="listing-fit">
                          <b>{item.fit_score}</b> fit
                        </span>
                        <button
                          className={`heart ${saved.includes(item.id) ? "saved" : ""}`}
                          onClick={() => props.onSave(item.id)}
                        >
                          <Heart
                            size={17}
                            fill={
                              saved.includes(item.id) ? "currentColor" : "none"
                            }
                          />
                        </button>
                        <small>{formatBand(item.price_band)}</small>
                        <span className="listing-photo-count">
                          <Layers3 size={12} /> {item.image_urls.length} photo
                          {item.image_urls.length === 1 ? "" : "s"}
                        </span>
                      </div>
                      <div className="listing-body">
                        <div className="listing-price">
                          <h3>
                            {formatUsd(item.price_usd)}
                            <small>{mode === "RENT" ? "/mo" : ""}</small>
                          </h3>
                          <span>USD</span>
                        </div>
                        <p>{item.title}</p>
                        <div className="listing-location">
                          <MapPin size={13} />
                          {item.district}
                        </div>
                        <div className="home-stats">
                          {item.beds !== undefined && (
                            <span>
                              <BedDouble size={15} /> {item.beds}
                            </span>
                          )}
                          {item.baths !== undefined && (
                            <span>
                              <Bath size={15} /> {item.baths}
                            </span>
                          )}
                          {item.area_sqm !== undefined && (
                            <span>{item.area_sqm} m²</span>
                          )}
                        </div>
                        <div className="proximity-stats">
                          {item.international_school_minutes_estimate !==
                            undefined && (
                            <span>
                              <GraduationCap size={13} /> ≈
                              {item.international_school_minutes_estimate} min
                              school
                            </span>
                          )}
                          {item.food_minutes_estimate !== undefined && (
                            <span>
                              <UtensilsCrossed size={13} /> ≈
                              {item.food_minutes_estimate} min food
                            </span>
                          )}
                        </div>
                        {item.fit_reasons[0] && (
                          <div className="fit-reason-preview">
                            <Check size={12} /> {item.fit_reasons[0]}
                          </div>
                        )}
                        {feedbackTarget === item.id ? (
                          <div className="listing-reasons">
                            <span>What does not fit?</span>
                            <button
                              className={
                                feedbackReason === "TOO_URBAN" ? "selected" : ""
                              }
                              onClick={() => setFeedbackReason("TOO_URBAN")}
                            >
                              Too urban
                            </button>
                            <button
                              className={
                                feedbackReason === "TOO_EXPENSIVE"
                                  ? "selected"
                                  : ""
                              }
                              onClick={() => setFeedbackReason("TOO_EXPENSIVE")}
                            >
                              Too expensive
                            </button>
                            <button
                              className={
                                feedbackReason === "TOO_SMALL" ? "selected" : ""
                              }
                              onClick={() => setFeedbackReason("TOO_SMALL")}
                            >
                              Too small
                            </button>
                            <button
                              className={
                                feedbackReason === "SCHOOL_TOO_FAR"
                                  ? "selected"
                                  : ""
                              }
                              onClick={() =>
                                setFeedbackReason("SCHOOL_TOO_FAR")
                              }
                            >
                              School too far
                            </button>
                            <button
                              className={
                                feedbackReason === "FOOD_TOO_FAR"
                                  ? "selected"
                                  : ""
                              }
                              onClick={() => setFeedbackReason("FOOD_TOO_FAR")}
                            >
                              Food too far
                            </button>
                            <input
                              value={feedbackNote}
                              maxLength={1000}
                              onChange={(event) =>
                                setFeedbackNote(event.target.value)
                              }
                              placeholder="Optional note — what specifically felt wrong?"
                              aria-label="Optional property feedback note"
                            />
                            <button
                              className="feedback-submit"
                              disabled={!feedbackReason}
                              onClick={() =>
                                props.onReason(
                                  item,
                                  feedbackReason,
                                  feedbackNote,
                                )
                              }
                            >
                              Save feedback
                            </button>
                            <button
                              aria-label="Close feedback"
                              onClick={() => selectFeedbackTarget("")}
                            >
                              <X size={13} />
                            </button>
                          </div>
                        ) : (
                          <button
                            className="listing-feedback text-button"
                            onClick={() => selectFeedbackTarget(item.id)}
                          >
                            {rejected.includes(item.id) ? (
                              <>
                                <Check size={13} /> Feedback saved
                              </>
                            ) : (
                              "Not for me"
                            )}
                          </button>
                        )}
                        <div className="listing-actions">
                          <button
                            className={`secondary small ${compare.includes(item.id) ? "compare-selected" : ""}`}
                            onClick={() => props.onCompare(item.id)}
                          >
                            {compare.includes(item.id) ? (
                              <Check size={13} />
                            ) : (
                              <SquareStack size={13} />
                            )}
                            {compare.includes(item.id) ? "Selected" : "Compare"}
                          </button>
                          <button
                            className="primary compact"
                            onClick={() => props.onDetail(item)}
                          >
                            View property
                          </button>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="live-search-state">
                  <Search size={22} />
                  <h3>
                    {listingSearch.returned === 0
                      ? "No properties match this profile"
                      : "No sourced listings in this price band"}
                  </h3>
                  <p>
                    {listingSearch.returned === 0
                      ? "Adjust your budget, property type, bedroom, or bathroom requirements. Roamstead will not add mismatched properties to fill the grid."
                      : "Roamstead will not fabricate results to fill the grid."}
                  </p>
                </div>
              )}
              {listingPages > 1 && (
                <div className="pagination">
                  <button
                    disabled={listingPage === 1}
                    onClick={() => props.onPage(listingPage - 1)}
                  >
                    <ChevronLeft size={15} /> Previous
                  </button>
                  <span>
                    Page {listingPage} of {listingPages}
                  </span>
                  <button
                    disabled={listingPage === listingPages}
                    onClick={() => props.onPage(listingPage + 1)}
                  >
                    Next <ArrowRight size={15} />
                  </button>
                </div>
              )}
            </>
          )}
        </>
      )}
    </div>
  );
}

const BRIEF_STAGES = [
  {
    phase: "EVIDENCE_PACKET",
    label: "Profile, listings, and Fit Scores locked",
    actor: "Deterministic tools",
    model: "Database + FitScoreTool",
    optional: false,
  },
  {
    phase: "SEMANTIC_MEMORY",
    label: "Relevant decision memory retrieved",
    actor: "SemanticMemoryTool",
    model: "gemini-embedding-001 · 768d",
    optional: false,
  },
  {
    phase: "LISTING_ANALYSIS",
    label: "Listing analysis",
    actor: "ListingAnalyst",
    model: "Gemini 3.5 Flash",
    optional: false,
  },
  {
    phase: "VISUAL_AUDIT",
    label: "Visual evidence audit",
    actor: "VisualEvidenceCritic",
    model: "Gemma 4 26B",
    optional: false,
  },
  {
    phase: "MEMORY_CONSISTENCY",
    label: "Decision memory consistency audit",
    actor: "MemoryConsistencyCritic",
    model: "Gemma 4 31B",
    optional: false,
  },
  {
    phase: "EVIDENCE_VERIFICATION",
    label: "Evidence verification",
    actor: "EvidenceVerifier",
    model: "Gemini 3.5 Flash",
    optional: false,
  },
  {
    phase: "CORRECTION",
    label: "Bounded correction",
    actor: "PartnerCoordinator",
    model: "Only if challenged",
    optional: true,
  },
  {
    phase: "BRIEF_COMPOSITION",
    label: "Decision Brief composed",
    actor: "BriefComposer",
    model: "Gemini 3.5 Flash",
    optional: false,
  },
  {
    phase: "DATABASE_SAVE",
    label: "Brief saved",
    actor: "DatabaseWriter",
    model: "Durable persistence",
    optional: false,
  },
] as const;

function DecisionBriefBuildModal({
  runId,
  events,
}: {
  runId: string;
  events: AgentEvent[];
}) {
  const currentEvent = events.at(-1);
  const isPhase = (event: AgentEvent, phase: string) => {
    const eventPhase = event.phase ?? String(event.public_payload.phase ?? "");
    return eventPhase === phase || eventPhase.startsWith(`${phase}_`);
  };
  const stageState = (phase: string, optional?: boolean) => {
    const matching = events.filter((event) => isPhase(event, phase));
    const completed = matching.some((event) =>
      [
        "SPECIALIST_COMPLETED",
        "SEMANTIC_MEMORY_COMPLETED",
        "TOOL_RESULT",
        "RUN_COMPLETED",
      ].includes(event.event_type),
    );
    const running =
      matching.some((event) =>
        [
          "SPECIALIST_STARTED",
          "SEMANTIC_MEMORY_STARTED",
          "AGENT_STATUS",
          "CORRECTION_REQUESTED",
        ].includes(event.event_type),
      ) && !completed;
    if (completed) return "complete";
    if (running) return "running";
    if (
      optional &&
      events.some(
        (event) =>
          event.phase === "BRIEF_COMPOSITION" ||
          event.phase === "DATABASE_SAVE",
      )
    )
      return "skipped";
    return "pending";
  };
  const completedCount = BRIEF_STAGES.filter(
    (stage) => stageState(stage.phase, stage.optional) === "complete",
  ).length;

  return (
    <div className="modal-backdrop brief-build-backdrop">
      <section
        className="brief-build-modal"
        data-testid="brief-build-modal"
        aria-live="polite"
        aria-label="Building your Decision Brief"
      >
        <header className="brief-build-header">
          <div>
            <span className="eyebrow">Live ADK orchestration</span>
            <h2>Building your Decision Brief</h2>
            <p>
              Each specialist result is saved before it appears here. You can
              reconnect without restarting the run.
            </p>
          </div>
          <span className="run-status">
            <i /> Running
          </span>
        </header>
        <div className="brief-model-flow">
          <span>
            <Database size={16} /> Vector memory
          </span>
          <ArrowRight size={14} />
          <span>
            <Bot size={16} /> Gemini analysis
          </span>
          <ArrowRight size={14} />
          <span className="gemma-model">
            <Layers3 size={16} /> Two Gemma audits
          </span>
          <ArrowRight size={14} />
          <span>
            <ShieldCheck size={16} /> Verified brief
          </span>
        </div>
        <div className="brief-build-body">
          <div className="brief-stage-list">
            {BRIEF_STAGES.map((stage, index) => {
              const state = stageState(stage.phase, stage.optional);
              const event = [...events]
                .reverse()
                .find((item) => isPhase(item, stage.phase));
              return (
                <article key={stage.phase} className={`brief-stage ${state}`}>
                  <span className="brief-stage-icon">
                    {state === "complete" ? (
                      <Check size={15} />
                    ) : state === "running" ? (
                      <Activity size={15} className="event-pulse" />
                    ) : (
                      index + 1
                    )}
                  </span>
                  <div>
                    <b>
                      {stage.label}
                      {stage.optional && <small> optional</small>}
                    </b>
                    <p>
                      {stage.actor} · {event?.model ?? stage.model}
                    </p>
                    {event?.summary && <span>{event.summary}</span>}
                  </div>
                  <em>{state === "skipped" ? "Not needed" : state}</em>
                </article>
              );
            })}
          </div>
          <aside className="brief-live-trace">
            <div>
              <span>Persisted run</span>
              <b>{runId ? runId.slice(0, 12) : "Queueing…"}</b>
            </div>
            <div className="brief-progress">
              <i
                style={{
                  width: `${Math.max(5, (completedCount / BRIEF_STAGES.length) * 100)}%`,
                }}
              />
            </div>
            <h3>Latest public activity</h3>
            {currentEvent ? (
              <div className="latest-event">
                <span className="event-sequence">{currentEvent.sequence}</span>
                <div>
                  <b>{currentEvent.actor}</b>
                  <p>{currentEvent.title}</p>
                  <small>{currentEvent.summary}</small>
                  {currentEvent.duration_ms !== undefined && (
                    <em>
                      {(currentEvent.duration_ms / 1000).toFixed(1)}s ·{" "}
                      {currentEvent.provider}
                    </em>
                  )}
                </div>
              </div>
            ) : (
              <div className="latest-event waiting">
                <Activity size={15} className="event-pulse" />
                <p>Creating the durable run and opening the event stream…</p>
              </div>
            )}
            <footer>
              <Database size={14} /> Events are database-first, resumable, and
              safe to reload.
            </footer>
          </aside>
        </div>
      </section>
    </div>
  );
}

function AgentActivity({
  events,
  priorBrief,
  onOpenBrief,
}: {
  events: AgentEvent[];
  priorBrief: DecisionBrief | null;
  onOpenBrief: () => void;
}) {
  const visible = events.slice(-4);
  return (
    <section className="agent-activity" aria-label="Agent and tool activity">
      <div className="activity-heading">
        <div>
          <Activity size={16} />
          <span>Partner activity</span>
          <small>Public summaries only</small>
        </div>
        {priorBrief && (
          <button onClick={onOpenBrief}>
            <FileText size={14} /> Resume saved brief
          </button>
        )}
      </div>
      <div className="activity-events">
        {visible.length ? (
          visible.map((event) => (
            <div
              key={event.id}
              className={
                event.event_type === "RECOVERABLE_ERROR" ? "warning" : ""
              }
            >
              {event.actor === "FitScoreTool" ||
              event.actor.includes("Store") ||
              event.actor.includes("Catalog") ? (
                <Database size={14} />
              ) : event.event_type === "RECOVERABLE_ERROR" ? (
                <AlertTriangle size={14} />
              ) : (
                <Bot size={14} />
              )}
              <span>
                <b>{event.title}</b>
                <small>{event.summary}</small>
              </span>
              <Check size={13} />
            </div>
          ))
        ) : (
          <div>
            <Bot size={14} />
            <span>
              <b>Partner ready</b>
              <small>Activity and evidence checks will appear here.</small>
            </span>
          </div>
        )}
      </div>
    </section>
  );
}

function WhyChanged({
  listingDeltas,
  explanation,
}: {
  listingDeltas: {
    listing_id: string;
    title: string;
    previous_rank: number;
    new_rank: number;
    previous_score: number;
    new_score: number;
  }[];
  explanation: string;
}) {
  const strongest = [...listingDeltas].sort(
    (a, b) => a.new_rank - a.previous_rank - (b.new_rank - b.previous_rank),
  )[0];
  return (
    <div className="why-changed">
      <div className="why-icon">
        <Sparkles size={18} />
      </div>
      <div className="why-copy">
        <div>
          <span>Why your ranking changed</span>
          <b>
            {strongest
              ? `${strongest.title} moved #${strongest.previous_rank} → #${strongest.new_rank}`
              : "Profile decision recorded"}
          </b>
        </div>
        <p>{explanation}</p>
        <div className="weight-delta">
          <span>Approved preference applied</span>
          {strongest && (
            <b>
              {strongest.previous_score} → {strongest.new_score} fit
            </b>
          )}
          <span className="unchanged">Hard constraints unchanged</span>
        </div>
      </div>
    </div>
  );
}

function MapPanel({
  landing,
  candidates,
  selected,
  onSelect,
  mobileMap,
}: {
  landing: boolean;
  candidates: Candidate[];
  selected?: string;
  onSelect: (id: string) => void;
  mobileMap: boolean;
}) {
  return (
    <section
      className={`map-panel ${mobileMap ? "mobile-map" : ""}`}
      aria-label="Map of Ho Chi Minh City recommendations"
    >
      <div className="map-search">
        <Search size={18} />
        <span>Ho Chi Minh City, Vietnam</span>
        <button>
          <ListFilter size={17} />
        </button>
      </div>
      <div className="map-layers">
        <button className="active">
          <Building2 size={15} /> Homes
        </button>
        <button>
          <Hospital size={15} /> Health
        </button>
        <button>
          <Waves size={15} /> Water
        </button>
        <button>
          <Trees size={15} /> Green
        </button>
      </div>
      <div className="map-canvas">
        <svg
          className="map-art"
          viewBox="0 0 900 900"
          preserveAspectRatio="xMidYMid slice"
          aria-hidden="true"
        >
          <rect width="900" height="900" fill="#eef2e6" />
          <path
            d="M-50 92C170 180 210 45 390 120S590 230 950 120"
            fill="none"
            stroke="#fff"
            strokeWidth="24"
          />
          <path
            d="M20 760C220 640 280 680 440 510S720 310 940 350"
            fill="none"
            stroke="#fff"
            strokeWidth="32"
          />
          <path
            d="M130 -40C220 190 130 410 290 580S560 720 610 940"
            fill="none"
            stroke="#fff"
            strokeWidth="22"
          />
          <path
            d="M775 -40C690 130 720 320 600 410S400 520 350 940"
            fill="none"
            stroke="#fff"
            strokeWidth="18"
          />
          <path
            d="M420 -30C395 150 540 220 490 355C438 498 555 552 650 612C760 681 725 795 830 940"
            fill="none"
            stroke="#b9e1ee"
            strokeWidth="72"
          />
          <path
            d="M420 -30C395 150 540 220 490 355C438 498 555 552 650 612C760 681 725 795 830 940"
            fill="none"
            stroke="#d8f1f7"
            strokeWidth="50"
          />
          <g fill="none" stroke="#d4d9d0" strokeWidth="5">
            <path d="M0 290L380 360L900 210" />
            <path d="M0 480L300 430L900 590" />
            <path d="M40 850L380 610L900 710" />
            <path d="M240 0L340 300L210 900" />
            <path d="M660 0L590 290L880 510" />
          </g>
          <g fill="#cfe6bf" opacity=".8">
            <path d="M52 550l145-40 42 100-160 58z" />
            <path d="M710 160l120-44 50 90-142 54z" />
            <path d="M82 110l92-40 34 82-106 39z" />
          </g>
          <g fill="#83928b" fontFamily="sans-serif" fontSize="17">
            <text x="80" y="245">
              BÌNH THẠNH
            </text>
            <text x="570" y="360">
              THU THIEM
            </text>
            <text x="190" y="645">
              DISTRICT 7
            </text>
            <text x="570" y="780">
              NHA BE
            </text>
            <text x="355" y="460">
              SAIGON RIVER
            </text>
          </g>
        </svg>
        {landing ? (
          <div className="map-intro-card">
            <span className="pulse-pin">
              <MapPin size={25} fill="currentColor" />
            </span>
            <div>
              <b>One city, many ways to live</b>
              <p>
                We’ll match verified HCMC properties against the life behind
                your filters.
              </p>
            </div>
          </div>
        ) : (
          candidates.map((item) => (
            <button
              key={item.id}
              className={`map-marker ${selected === item.id ? "selected" : ""}`}
              style={{ left: `${item.map_x}%`, top: `${item.map_y}%` }}
              onClick={() => onSelect(item.id)}
            >
              <span>{item.score}</span>
              <small>{item.name}</small>
            </button>
          ))
        )}
        {!landing && selected && (
          <div className="selected-map-card">
            <span>Selected neighborhood</span>
            <b>{candidates.find((item) => item.id === selected)?.name}</b>
            <p>
              <Route size={14} /> Routes shown are demo estimates
            </p>
          </div>
        )}
      </div>
      <div className="map-controls">
        <button>
          <Navigation size={18} />
        </button>
        <button>+</button>
        <button>−</button>
      </div>
      <div className="map-attribution">Stylized demo map · HCMC</div>
    </section>
  );
}

function ClarificationPrompt({
  clarification,
  busy,
  onAnswer,
}: {
  clarification: ClarificationTurn;
  busy: boolean;
  onAnswer: (optionId: string) => void;
}) {
  return (
    <div className="prompt-backdrop">
      <section className="clarification-prompt">
        <div className="prompt-spark">
          <Sparkles size={24} />
        </div>
        <span className="eyebrow plain">
          One adaptive question · {clarification.eligible_listing_count}{" "}
          qualified listings checked
        </span>
        <h2>{clarification.question}</h2>
        <div className="clarification-why">
          <Info size={16} />
          <p>
            <b>Why I’m asking</b>
            {clarification.why_asked}
          </p>
        </div>
        <div className="clarification-options">
          {clarification.options.map((option) => (
            <button
              key={option.id}
              disabled={busy}
              onClick={() => onAnswer(option.id)}
              className={
                option.preference_key ? "option-impact" : "option-balance"
              }
            >
              <span>{option.label}</span>
              <small>{option.impact_summary}</small>
              <ArrowRight size={16} />
            </button>
          ))}
        </div>
        <p className="clarification-trust">
          <ShieldCheck size={14} /> Your answer creates a proposal. It cannot
          change your profile until you approve it.
        </p>
      </section>
    </div>
  );
}

function PreferencePrompt({
  proposal,
  memory,
  busy,
  onDecision,
}: {
  proposal: Proposal;
  memory: MemoryContextPacket | null;
  busy: boolean;
  onDecision: (decision: "ACCEPT" | "SOFTEN" | "REJECT") => void;
}) {
  return (
    <div className="prompt-backdrop">
      <section className="preference-prompt">
        <div className="prompt-spark">
          <Sparkles size={24} />
        </div>
        <span className="eyebrow plain">
          {proposal.source_clarification_id
            ? "Counterfactual proposal"
            : `Pattern noticed · ${proposal.evidence_count} signals`}
        </span>
        <h2>Should “{proposal.label}” matter more?</h2>
        <p>
          {proposal.rationale} I will not change your Decision Profile until you
          choose.
        </p>
        {proposal.predicted_impact && (
          <div className="proposal-impact">
            <Activity size={15} />
            {proposal.predicted_impact}
          </div>
        )}
        {memory && memory.matches.length > 0 && (
          <div className="relevant-memory">
            <Database size={16} />
            <div>
              <b>Relevant decision memory</b>
              <p>{memory.matches[0].text}</p>
              <small>
                {memory.selected_count} of {memory.considered_count} related
                memories · {memory.model}
              </small>
            </div>
          </div>
        )}
        <div className="proposal-change">
          <span>{proposal.label} weight</span>
          <b>{Math.round(proposal.old_weight * 100)}</b>
          <ArrowRight size={17} />
          <b className="new-weight">
            {Math.round(proposal.proposed_weight * 100)}
          </b>
        </div>
        <div className="prompt-actions">
          <button
            className="primary"
            disabled={busy}
            onClick={() => onDecision("ACCEPT")}
          >
            <Check size={17} /> Yes, update my profile
          </button>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => onDecision("SOFTEN")}
          >
            Keep it softer
          </button>
          <button
            className="text-button"
            disabled={busy}
            onClick={() => onDecision("REJECT")}
          >
            No change
          </button>
        </div>
      </section>
    </div>
  );
}

function PropertyDetail({
  mode,
  listing,
  evidence,
  saved,
  comparing,
  onClose,
  onSave,
  onCompare,
}: {
  mode: HousingMode;
  listing: Listing;
  evidence: Evidence;
  saved: boolean;
  comparing: boolean;
  onClose: () => void;
  onSave: () => void;
  onCompare: () => void;
}) {
  const photos = listing.image_urls.length
    ? listing.image_urls
    : [listing.image_url];
  const [photoIndex, setPhotoIndex] = useState(0);
  const previousPhoto = () =>
    setPhotoIndex((current) => (current - 1 + photos.length) % photos.length);
  const nextPhoto = () =>
    setPhotoIndex((current) => (current + 1) % photos.length);
  return (
    <div className="modal-backdrop">
      <section className="property-modal">
        <div
          className="property-photo live-detail-hero"
          style={{ backgroundImage: `url(${photos[photoIndex]})` }}
        >
          <button
            className="modal-close"
            onClick={onClose}
            aria-label="Close property"
          >
            <X size={20} />
          </button>
          <span className="live-badge large">
            <span /> Verified photo gallery
          </span>
          <button
            className="gallery-nav gallery-prev"
            onClick={previousPhoto}
            aria-label="Previous property photo"
            disabled={photos.length === 1}
          >
            <ChevronLeft size={23} />
          </button>
          <button
            className="gallery-nav gallery-next"
            onClick={nextPhoto}
            aria-label="Next property photo"
            disabled={photos.length === 1}
          >
            <ChevronRight size={23} />
          </button>
          <span className="property-gallery-count">
            <Layers3 size={13} /> {photoIndex + 1} / {photos.length}
          </span>
        </div>
        <div
          className="property-thumbnails"
          aria-label="Property photo gallery"
        >
          {photos.map((photo, index) => (
            <button
              key={photo}
              className={index === photoIndex ? "active" : ""}
              style={{ backgroundImage: `url(${photo})` }}
              onClick={() => setPhotoIndex(index)}
              aria-label={`View property photo ${index + 1}`}
              aria-current={index === photoIndex ? "true" : undefined}
            />
          ))}
          {photos.length === 1 && (
            <span className="single-photo-note">
              Only one exact-listing photo is currently verified.
            </span>
          )}
        </div>
        <div className="property-content">
          <div className="property-main">
            <span className="eyebrow plain">
              {listing.property_type} · For {mode === "BUY" ? "sale" : "rent"} ·{" "}
              {listing.district}
            </span>
            <div className="property-title">
              <div>
                <h2>
                  {formatUsd(listing.price_usd)}{" "}
                  {mode === "RENT" && <small>/ month</small>}
                </h2>
                <p>{listing.title}</p>
              </div>
              <div className="big-fit">
                <b>{listing.fit_score}</b>
                <span>profile fit</span>
              </div>
            </div>
            <div className="property-stats">
              {listing.beds !== undefined && (
                <span>
                  <BedDouble /> <b>{listing.beds}</b> beds
                </span>
              )}
              {listing.baths !== undefined && (
                <span>
                  <Bath /> <b>{listing.baths}</b> baths
                </span>
              )}
              {listing.area_sqm !== undefined && (
                <span>
                  <SquareStack /> <b>{listing.area_sqm}</b> m²
                </span>
              )}
            </div>
            <h3>Why it fits your profile</h3>
            <div className="fit-grid">
              <div>
                <Sparkles />
                <b>{listing.fit_score}/100</b>
                <span>weighted profile match</span>
              </div>
              <div>
                <MapPin />
                <b>{listing.district}</b>
                <span>location signals</span>
              </div>
              {listing.international_school_minutes_estimate !== undefined && (
                <div>
                  <GraduationCap />
                  <b>≈ {listing.international_school_minutes_estimate} min</b>
                  <span>international school · district estimate</span>
                </div>
              )}
              {listing.food_minutes_estimate !== undefined && (
                <div>
                  <UtensilsCrossed />
                  <b>≈ {listing.food_minutes_estimate} min</b>
                  <span>food & daily needs · district estimate</span>
                </div>
              )}
              {listing.area_sqm !== undefined && (
                <div>
                  <SquareStack />
                  <b>{listing.area_sqm} m²</b>
                  <span>reported area</span>
                </div>
              )}
              <div>
                <Search />
                <b>
                  {new Date(listing.source_checked_at).toLocaleDateString()}
                </b>
                <span>web search checked</span>
              </div>
            </div>
            <div className="fit-explanation">
              <div className="fit-reasons">
                {listing.fit_reasons.map((reason) => (
                  <span key={reason}>
                    <Check size={13} />
                    {reason}
                  </span>
                ))}
              </div>
              <div className="fit-breakdown">
                {Object.entries(listing.fit_breakdown).map(([key, score]) => (
                  <div key={key}>
                    <span>
                      {FIT_FACTOR_LABELS[key] ?? key}
                      <b>{score}</b>
                    </span>
                    <div>
                      <i style={{ width: `${score}%` }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
            <div className="evidence-card">
              <div className="evidence-top">
                <div className="evidence-icon">
                  <ShieldCheck size={20} />
                </div>
                <div>
                  <span>
                    {mode === "BUY"
                      ? "Cross-border purchase"
                      : "Cross-border lease"}
                  </span>
                  <b>Requires verification</b>
                </div>
                <span className="confidence">
                  {evidence.confidence} confidence
                </span>
              </div>
              <p>
                {mode === "BUY"
                  ? evidence.summary
                  : "Treat advertised rent and availability as provisional. Verify the landlord or authorized agent, building rules, permitted use, deposit, utilities, registration responsibilities and termination terms before signing."}
              </p>
              <div className="evidence-meta">
                <a href={evidence.source_url} target="_blank" rel="noreferrer">
                  {evidence.source_title} <ExternalLink size={13} />
                </a>
                <span>Checked {evidence.last_checked}</span>
              </div>
              <div className="verify-step">
                <Info size={15} />
                <span>
                  {mode === "BUY"
                    ? "Before any deposit, confirm the buyer, project, unit quota, term and transaction structure with a qualified independent local professional."
                    : "Before paying a deposit, have the lease and the landlord’s authority independently verified; request a bilingual contract if needed."}
                </span>
              </div>
            </div>
          </div>
          <aside className="property-actions">
            <span>Original source</span>
            <h3>Verify availability and details</h3>
            <a
              className="primary source-cta"
              href={listing.source_url}
              target="_blank"
              rel="noreferrer"
            >
              Open original listing <ExternalLink size={16} />
            </a>
            <button className="secondary" onClick={onSave}>
              {saved ? <Check size={17} /> : <Heart size={17} />}
              {saved ? "Saved" : mode === "BUY" ? "Save home" : "Save rental"}
            </button>
            <button className="secondary" onClick={onCompare}>
              {comparing ? <Check size={17} /> : <SquareStack size={17} />}
              {comparing ? "Added to compare" : "Compare"}
            </button>
            <p>
              <ShieldCheck size={14} /> Roamstead shows search-indexed facts.
              Confirm price, availability, photos and agent identity on the
              source page.
            </p>
          </aside>
        </div>
      </section>
    </div>
  );
}

function DecisionBriefModal({
  brief,
  events,
  onClose,
}: {
  brief: DecisionBrief;
  events: AgentEvent[];
  onClose: () => void;
}) {
  const audit = brief.visual_audit;
  const memoryContext = brief.memory_context;
  const memoryAudit = brief.memory_audit;
  return (
    <div className="modal-backdrop">
      <section className="brief-modal">
        <header className="brief-header">
          <div>
            <span className="eyebrow plain">
              Persistent agent run · Profile v{brief.profile_version}
            </span>
            <h2>{brief.title}</h2>
            <p>{brief.executive_summary}</p>
          </div>
          <button
            className="modal-close static"
            onClick={onClose}
            aria-label="Close Decision Brief"
          >
            <X size={20} />
          </button>
        </header>
        <div className="brief-runtime">
          <span>
            <Bot size={15} /> Google ADK specialist orchestration
          </span>
          <span>
            <Layers3 size={15} />{" "}
            {audit?.succeeded
              ? `${audit.model} visual audit succeeded`
              : "Visual audit unavailable"}
          </span>
          <span>
            <Database size={15} />{" "}
            {memoryContext?.status === "READY"
              ? `${memoryContext.model} memory retrieval succeeded`
              : "Semantic memory unavailable"}
          </span>
          <span>
            <ShieldCheck size={15} />{" "}
            {memoryAudit?.succeeded
              ? `${memoryAudit.model} consistency audit succeeded`
              : "Memory consistency audit unavailable"}
          </span>
          <span>
            <Database size={15} /> Saved to the database
          </span>
          <span
            className={brief.degraded ? "runtime-degraded" : "runtime-success"}
          >
            {brief.degraded ? (
              <AlertTriangle size={15} />
            ) : (
              <ShieldCheck size={15} />
            )}
            {brief.degraded
              ? "Completed in degraded mode"
              : "All evidence stages completed"}
          </span>
        </div>
        {brief.models_used.length > 0 && (
          <div className="brief-model-proof">
            <b>Model proof</b>
            {brief.models_used.map((model) => (
              <span key={model}>{model}</span>
            ))}
          </div>
        )}
        {events.length > 0 && (
          <details className="brief-events" open>
            <summary>
              Completed agent trace · {events.length} persisted events
            </summary>
            {events.map((event) => (
              <div
                key={event.id}
                className={
                  event.event_type === "RUN_DEGRADED" ||
                  event.event_type === "RECOVERABLE_ERROR"
                    ? "warning"
                    : ""
                }
              >
                <span className="event-sequence">{event.sequence}</span>
                <div>
                  <b>
                    {event.actor} · {event.title}
                  </b>
                  <p>{event.summary}</p>
                  <small>
                    {event.model && `${event.model} · `}
                    {event.provider}
                    {event.duration_ms !== undefined &&
                      ` · ${(event.duration_ms / 1000).toFixed(1)}s`}
                  </small>
                </div>
                {event.event_type === "RUN_DEGRADED" ||
                event.event_type === "RECOVERABLE_ERROR" ? (
                  <AlertTriangle size={15} />
                ) : (
                  <Check size={15} />
                )}
              </div>
            ))}
          </details>
        )}
        {audit && (
          <section
            className={`brief-overall-audit ${audit.verdict.toLowerCase()}`}
          >
            <div>
              <span>
                <Layers3 size={17} /> Gemma visual evidence audit
              </span>
              <b>{audit.verdict}</b>
            </div>
            <p>{audit.summary}</p>
            <small>
              {audit.analyzed_photo_count} real cached photo
              {audit.analyzed_photo_count === 1 ? "" : "s"} analyzed ·{" "}
              {audit.model} · {audit.provider}
            </small>
            {audit.challenged_claims.length > 0 && (
              <div>
                {audit.challenged_claims.map((claim) => (
                  <span key={claim}>
                    <AlertTriangle size={12} />
                    {claim}
                  </span>
                ))}
              </div>
            )}
          </section>
        )}
        {memoryContext && (
          <section
            className={`brief-memory-context ${memoryContext.status.toLowerCase()}`}
          >
            <div>
              <span>
                <Database size={17} /> Relevant decision memory
              </span>
              <b>{memoryContext.selected_count} selected</b>
            </div>
            <p>
              Considered {memoryContext.considered_count}, selected{" "}
              {memoryContext.selected_count}, and excluded{" "}
              {memoryContext.excluded_count}. This context never changes hard
              filters or Fit Scores.
            </p>
            {memoryContext.matches.map((item) => (
              <article key={item.memory_id}>
                <b>{item.preference_key?.replaceAll("_", " ") ?? item.kind}</b>
                <span>{item.text}</span>
                <small>
                  {item.city ?? "Cross-city memory"} · cosine distance{" "}
                  {item.cosine_distance.toFixed(3)}
                </small>
              </article>
            ))}
            <small>
              {memoryContext.model} · {memoryContext.dimension} dimensions
            </small>
          </section>
        )}
        {memoryAudit && (
          <section
            className={`brief-memory-audit ${memoryAudit.verdict.toLowerCase()}`}
          >
            <div>
              <span>
                <ShieldCheck size={17} /> Gemma decision-memory audit
              </span>
              <b>{memoryAudit.verdict}</b>
            </div>
            <p>{memoryAudit.summary}</p>
            {[
              ...memoryAudit.conflicting_preferences,
              ...memoryAudit.unsupported_user_assumptions,
              ...memoryAudit.omitted_tradeoffs,
            ].map((item) => (
              <span key={item}>
                <AlertTriangle size={12} />
                {item}
              </span>
            ))}
            {memoryAudit.suggested_questions.map((item) => (
              <span key={item}>
                <Info size={12} />
                {item}
              </span>
            ))}
            <small>
              {memoryAudit.model} · {memoryAudit.provider} ·{" "}
              {(memoryAudit.duration_ms / 1000).toFixed(1)}s
            </small>
          </section>
        )}
        <div className="brief-properties">
          {brief.properties.map((property, index) => {
            const propertyAudit = property.visual_audit;
            return (
              <article key={property.listing_id}>
                <div
                  className="brief-property-photo"
                  style={{ backgroundImage: `url(${property.image_urls[0]})` }}
                >
                  <span>
                    #{index + 1} · {property.fit_score} fit
                  </span>
                </div>
                <div className="brief-property-copy">
                  <h3>{property.title}</h3>
                  <p>
                    {property.district} · {formatUsd(property.price_usd)}
                    {property.transaction_mode === "RENT" ? "/month" : ""}
                  </p>
                  <div className="claim-list">
                    {property.evidence.map((claim) => (
                      <div key={claim.id}>
                        <span
                          className={`claim-status ${claim.status.toLowerCase()}`}
                        >
                          {claim.status}
                        </span>
                        <b>{claim.label}</b>
                        <span>{claim.value}</span>
                        <small>{claim.explanation}</small>
                      </div>
                    ))}
                  </div>
                  {propertyAudit && (
                    <section
                      className={`property-visual-audit ${propertyAudit.verdict.toLowerCase()}`}
                    >
                      <header>
                        <span>
                          <Layers3 size={14} /> Gemma visual evidence
                        </span>
                        <b>{propertyAudit.verdict}</b>
                      </header>
                      {propertyAudit.images.map((image) => (
                        <div
                          className="audit-image-result"
                          key={`${property.listing_id}-${image.image_index}`}
                        >
                          <Image
                            src={image.image_url}
                            width={58}
                            height={52}
                            unoptimized
                            alt={`Audited listing photo ${image.image_index + 1}`}
                          />
                          <div>
                            <span className="image-classification">
                              {image.classification.replace("_", " ")}
                            </span>
                            <small>{image.confidence} confidence</small>
                            {image.observations.map((observation) => (
                              <p key={observation}>
                                <Check size={11} />
                                {observation}
                              </p>
                            ))}
                            {image.warnings.map((warning) => (
                              <p className="audit-warning" key={warning}>
                                <AlertTriangle size={11} />
                                {warning}
                              </p>
                            ))}
                          </div>
                        </div>
                      ))}
                      {propertyAudit.unsupported_claims.map((claim) => (
                        <p className="audit-warning" key={claim}>
                          <AlertTriangle size={12} />
                          Unsupported claim: {claim}
                        </p>
                      ))}
                      {propertyAudit.missing_evidence.map((item) => (
                        <p className="audit-warning" key={item}>
                          <Info size={12} />
                          Missing evidence: {item}
                        </p>
                      ))}
                    </section>
                  )}
                  <div className="brief-tradeoffs">
                    <b>Tradeoffs</b>
                    {property.tradeoffs.map((item) => (
                      <p key={item}>
                        <Info size={13} />
                        {item}
                      </p>
                    ))}
                  </div>
                  {property.verification_questions.length > 0 && (
                    <div className="verification-questions">
                      <b>Ask before committing</b>
                      {property.verification_questions
                        .slice(0, 4)
                        .map((item) => (
                          <p key={item}>{item}</p>
                        ))}
                    </div>
                  )}
                  <a
                    href={property.source_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Re-check original source <ExternalLink size={13} />
                  </a>
                </div>
              </article>
            );
          })}
        </div>
        <div className="brief-decision">
          <div>
            <h3>Recommended decision posture</h3>
            <p>{brief.recommendation}</p>
            <h3>Next actions</h3>
            <ol>
              {brief.next_actions.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ol>
          </div>
          <aside>
            <h3>Unknown until verified</h3>
            {brief.unknowns.map((item) => (
              <p key={item}>
                <AlertTriangle size={14} />
                {item}
              </p>
            ))}
          </aside>
        </div>
        <footer className="brief-footer">
          <ShieldCheck size={16} />
          <span>{brief.disclaimer}</span>
          <button className="primary compact" onClick={onClose}>
            Done
          </button>
        </footer>
      </section>
    </div>
  );
}

function MovePlan({
  plan,
  onClose,
}: {
  plan: ActionPlan;
  onClose: () => void;
}) {
  return (
    <div className="modal-backdrop">
      <section className="plan-modal">
        <div className="plan-header">
          <div className="plan-icon">
            <Navigation size={22} fill="currentColor" />
          </div>
          <div>
            <span className="eyebrow plain">Action plan ready</span>
            <h2>{plan.title}</h2>
          </div>
          <button className="modal-close static" onClick={onClose}>
            <X size={20} />
          </button>
        </div>
        <div className="shortlist-strip">
          <span>Your shortlist</span>
          {plan.shortlist.map((item) => (
            <b key={item}>{item}</b>
          ))}
        </div>
        <div className="plan-columns">
          <div>
            <h3>Your next four moves</h3>
            <ol>
              {plan.steps.map((step, index) => (
                <li key={step.phase}>
                  <span>{index + 1}</span>
                  <div>
                    <b>{step.phase}</b>
                    <p>{step.task}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
          <aside>
            <h3>Resolve before committing</h3>
            {plan.unresolved_questions.map((item) => (
              <p key={item}>
                <Info size={15} />
                {item}
              </p>
            ))}
            <div className="plan-trust">
              <ShieldCheck size={18} />
              <span>
                This plan organizes research. It is not legal or financial
                advice.
              </span>
            </div>
          </aside>
        </div>
        <button className="primary plan-done" onClick={onClose}>
          Done for now <Check size={17} />
        </button>
      </section>
    </div>
  );
}
