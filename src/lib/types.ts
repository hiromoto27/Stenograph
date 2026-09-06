export type RecordMode = "on_demand" | "continuous";
export type Speaker = "me" | "other" | "unknown";
export type UtteranceKind = "speech" | "decision" | "risk" | "blocker";

export type Utterance = {
  id: string;
  text: string;
  createdAt: string;
  taskId: string | null;
  confidence: number;
  autoAssigned: boolean;
  confirmed: boolean;
  meetingId: string | null;
  speaker: Speaker;
  kind: UtteranceKind;
};

export type Meeting = {
  id: string;
  title: string;
  startedAt: string;
  endedAt: string | null;
  protocolId: string | null;
};

export type Task = {
  id: string;
  title: string;
  notes: string;
  createdAt: string;
  dueAt: string | null;
  remindAt: string | null;
  reminded: boolean;
  repeatMin: number | null;
  positive: Record<string, number>;
  negative: Record<string, number>;
  links: Record<string, number>;
  hits: number;
  misses: number;
};

export type Protocol = {
  id: string;
  title: string;
  createdAt: string;
  body: string;
  taskIds: string[];
  meetingId: string | null;
};

export type ClarifyCandidate = {
  taskId: string;
  title: string;
  score: number;
  overlap: string[];
};

export type ClarifyPrompt = {
  utteranceId: string;
  text: string;
  suggestedTaskId: string | null;
  suggestedTitle: string | null;
  confidence: number;
  reason: string;
  candidates: ClarifyCandidate[];
};

export type Settings = {
  recordMode: RecordMode;
  language: string;
  threshold: number;
  notify: boolean;
  inputDeviceId: string | "";
  engine: "browser" | "whisper" | "auto" | "grok";
  wizardDone: boolean;
  pauseSec: number;
  compactMode: boolean;
  autoDocs: boolean;
  templateId: string;
  simdMode: "auto" | "off" | "fixed" | "relaxed";
  computeDevice: "auto" | "webgpu" | "wasm";
};

export type ProtocolTemplate = { id: string; name: string; title: string; body: string };
export type InstructionStep = { id: string; text: string; href: string; image: string | null };
export type Instruction = { id: string; title: string; taskId: string | null; createdAt: string; steps: InstructionStep[] };
export type MapLink = { a: string; b: string; label: string };

export type AppState = {
  settings: Settings;
  tasks: Task[];
  utterances: Utterance[];
  protocols: Protocol[];
  instructions: Instruction[];
  templates: ProtocolTemplate[];
  meetings: Meeting[];
  activeMeetingId: string | null;
  mapLinks: MapLink[];
  hiddenPairs: string[];
};
