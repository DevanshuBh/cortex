/** Demo data for the static demo and tests. Answers mirror the shape of real CORTEX output. */

export const demoDocuments = [
  ["concepts__workloads__controllers__deployment.md", "Deployments", 38],
  ["concepts__workloads__controllers__replicaset.md", "ReplicaSet", 17],
  ["concepts__workloads__pods__probes.md", "Liveness, Readiness, and Startup Probes", 12],
  ["concepts__services-networking__service.md", "Service", 61],
  ["concepts__storage__persistent-volumes.md", "Persistent Volumes", 58],
  ["concepts__configuration__secret.md", "Secrets", 40],
].map(([filename, title, chunks], i) => ({
  id: `00000000-0000-4000-8000-00000000000${i}`,
  title: String(title),
  filename: String(filename),
  mime: "text/markdown",
  size_bytes: 12000 + i * 900,
  status: "ready" as const,
  error: null,
  chunk_count: Number(chunks),
  created_at: "2026-11-15T09:00:00Z",
  updated_at: "2026-11-15T09:05:00Z",
}));

export const demoEvidence = [
  {
    n: 1, chunk_id: "11111111-0000-4000-8000-000000000001", document_id: demoDocuments[0]!.id, title: "Deployments",
    heading: "Deployments", source: "rerank",
    text: "A Deployment provides declarative updates for Pods and ReplicaSets.\n\nYou describe a desired state in a Deployment, and the Deployment controller changes the actual state to the desired state at a controlled rate.",
  },
  {
    n: 2, chunk_id: "11111111-0000-4000-8000-000000000002", document_id: demoDocuments[1]!.id, title: "ReplicaSet",
    heading: "ReplicaSet", source: "graph",
    text: "A ReplicaSet's purpose is to maintain a stable set of replica Pods running at any given time. As such, it is often used to guarantee the availability of a specified number of identical Pods.",
  },
  {
    n: 3, chunk_id: "11111111-0000-4000-8000-000000000003", document_id: demoDocuments[1]!.id, title: "ReplicaSet",
    heading: "ReplicaSet > When to use a ReplicaSet", source: "rerank",
    text: "A Deployment is a higher-level concept that manages ReplicaSets and provides declarative updates to Pods along with a lot of other useful features. Therefore, we recommend using Deployments instead of directly using ReplicaSets.",
  },
];

export const demoAnswer =
  "A Deployment manages **ReplicaSets**: it provides declarative updates for Pods and ReplicaSets, and its controller moves the actual state towards the desired state at a controlled rate [1][3].\n\n" +
  "Each ReplicaSet in turn keeps a stable set of replica **Pods** running at any given time [2]. So the chain is Deployment → ReplicaSet → Pods [1][2].";

export const demoGraphPaths = [
  { text: "Deployment -[MANAGES]-> ReplicaSet -[MAINTAINS]-> Pod", nodes: ["Deployment", "ReplicaSet", "Pod"],
    relations: ["MANAGES", "MAINTAINS"], chunk_ids: [demoEvidence[2]!.chunk_id, demoEvidence[1]!.chunk_id] },
  { text: "Deployment -[UPDATES]-> Pod", nodes: ["Deployment", "Pod"], relations: ["UPDATES"], chunk_ids: [demoEvidence[0]!.chunk_id] },
];

const step = (t: number, agent: string, action: string, newEvidence: number, steps: number, tokens: number) => ({
  t, agent, action, new_evidence: newEvidence, detail: {}, steps_used: steps, tokens_used: tokens,
  cost_usd: tokens * 0.0000008, remaining: { steps: 8 - steps, tokens: 24000 - tokens, seconds: 200 },
});

export const demoSteps = [
  step(0.4, "supervisor", "route: relationship", 0, 0, 180),
  step(1.6, "researcher", "search: What does a Deployment manage, and what do those objects in turn keep running?", 3, 1, 180),
  step(2.9, "supervisor", "assess evidence", 0, 2, 1150),
];

/** Recall@10 with 95 % bootstrap intervals from the real evaluation run of 2026-11-15 (eval/reports). */
const MEASURED: Record<string, [number, number, number]> = {
  dense: [0.93, 0.86, 0.982], sparse: [0.482, 0.36, 0.614], fused: [0.868, 0.781, 0.947], reranked: [0.956, 0.895, 1.0],
};
export const demoRuns = [{
  id: 1, created_at: "2026-11-15T12:07:50Z", name: "retrieval", git_commit: null, config: {},
  metrics: Object.fromEntries(Object.entries(MEASURED).map(([k, [value, low, high]]) => [k, { "recall@10": { value, low, high } }])),
}];
