# Roamstead — Google Cloud Production Architecture

This diagram represents the production deployment described in `GOOGLE_CLOUD_DEPLOYMENT_PLAN.md`. It intentionally uses Firestore rather than Cloud SQL because Roamstead stores document-oriented decision memory, listings, and durable agent traces—not relational PostgreSQL data.

```mermaid
graph TB
    USER["U.S. buyer or renter<br/>Desktop / mobile browser"]
    MAPS["Google Maps Platform<br/>Maps JavaScript + Geocoding"]

    subgraph GCP["Google Cloud Platform · Production"]
        direction TB

        subgraph EDGE["GLOBAL EDGE & SECURITY"]
            direction LR
            DNS["Cloud DNS<br/>roamstead domain"]
            ARMOR["Cloud Armor<br/>WAF + rate policies"]
            LB["Global HTTPS Load Balancer<br/>Managed TLS · serverless NEG"]
        end

        subgraph REGION["SERVERLESS APPLICATION · us-central1"]
            direction TB
            WEB["Cloud Run · roamstead-web<br/>Next.js 16 + React 19<br/>REST/SSE proxy · no server secrets"]
            API["Cloud Run · roamstead-api<br/>FastAPI + Google ADK<br/>PartnerCoordinator · deterministic Fit Score"]
        end

        subgraph AI["GOOGLE AI MODEL LAYER"]
            direction LR
            EMBED["Gemini Embedding 001<br/>768d semantic retrieval"]
            GEMINI["Gemini 3.5 Flash<br/>analysis · verification · brief composition"]
            GEMMA26["Gemma 4 26B<br/>multimodal VisualEvidenceCritic"]
            GEMMA31["Gemma 4 31B<br/>MemoryConsistencyCritic"]
        end

        subgraph DATA["DURABLE DATA & EVIDENCE"]
            direction LR
            FS["Firestore Native + vector index<br/>profiles · semantic memory · revisions<br/>listings · runs/events · briefs"]
            GCS["Cloud Storage<br/>private verified listing photos"]
        end

        subgraph ASYNC["WEEKLY REAL-DATA PIPELINE"]
            direction LR
            SCHED["Cloud Scheduler<br/>Monday 09:00 UTC"]
            JOB["Cloud Run Job<br/>Gemini-grounded catalog refresh"]
            PUB["Pub/Sub<br/>completion / failure events"]
        end

        subgraph PLATFORM["SECURITY, DELIVERY & OPERATIONS"]
            direction LR
            SECRET["Secret Manager<br/>Gemini credential"]
            BUILD["Cloud Build<br/>test + container build"]
            AR["Artifact Registry<br/>immutable API/web images"]
            OPS["Cloud Logging & Monitoring<br/>request IDs · alerts · audit proof"]
        end
    end

    USER -->|HTTPS| DNS
    DNS --> LB
    ARMOR -. protects .-> LB
    LB -->|serverless NEG| WEB
    USER -->|map tiles + geocoding| MAPS
    WEB -->|REST + resumable SSE| API

    API -->|768d query embedding| EMBED
    EMBED -->|profile-isolated cosine KNN| FS
    API -->|ADK specialist calls| GEMINI
    GEMINI -->|public claims + real photos| GEMMA26
    GEMMA26 -->|typed visual audit| GEMMA31
    GEMMA31 -->|typed memory audit| GEMINI
    API -->|durable state| FS
    API -->|private image reads| GCS
    SECRET -. runtime secret .-> API

    SCHED -. weekly trigger .-> JOB
    SECRET -. runtime secret .-> JOB
    JOB -. atomic catalog writes .-> FS
    JOB -. verified photo writes .-> GCS
    JOB -. status event .-> PUB

    BUILD -. publish .-> AR
    AR -. deploy .-> WEB
    AR -. deploy .-> API
    API -. structured logs .-> OPS
    JOB -. execution logs .-> OPS

    classDef blue fill:#4285f4,stroke:#1a5fbf,color:#ffffff,stroke-width:2px;
    classDef red fill:#ea4335,stroke:#b3261e,color:#ffffff,stroke-width:2px;
    classDef yellow fill:#fbbc05,stroke:#b07b00,color:#202124,stroke-width:2px;
    classDef green fill:#34a853,stroke:#1e7e3e,color:#ffffff,stroke-width:2px;
    classDef purple fill:#7e57c2,stroke:#5e35b1,color:#ffffff,stroke-width:2px;
    classDef surface fill:#ffffff,stroke:#c8d7eb,color:#17324d,stroke-width:2px;

    class DNS,LB,WEB,API,FS,GCS,BUILD,AR blue;
    class ARMOR,SECRET red;
    class SCHED,PUB yellow;
    class JOB,OPS green;
    class EMBED,GEMINI,GEMMA26,GEMMA31 purple;
    class USER,MAPS surface;

    style GCP fill:#f7faff,stroke:#4285f4,stroke-width:3px,color:#17324d
    style EDGE fill:#ffffff,stroke:#d5e2f3,stroke-width:2px,color:#49627d
    style REGION fill:#f5f9ff,stroke:#9ec1f5,stroke-width:2px,color:#49627d
    style AI fill:#faf7ff,stroke:#c8b5ef,stroke-width:2px,color:#5e35b1
    style DATA fill:#f6fbff,stroke:#a9caee,stroke-width:2px,color:#49627d
    style ASYNC fill:#fffaf0,stroke:#f4cc65,stroke-width:2px,color:#7b5b0b
    style PLATFORM fill:#f6fbf7,stroke:#9ed4ae,stroke-width:2px,color:#285d37
```

## Reading the diagram

- Solid blue paths are live user request and agent/model flows.
- Dashed paths are policies, deployment, secrets, scheduled work, persistence, and observability.
- The browser talks only to the public web edge and Google Maps Platform; Gemini, Firestore, Storage, and privileged credentials stay behind the FastAPI boundary.
- Fit Scores and hard filters remain deterministic. Gemini and Gemma interpret and verify evidence but do not alter prices, filters, or profile weights.
