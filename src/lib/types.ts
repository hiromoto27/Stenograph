export type RecordMode = "on_demand" | "continuous";

export type Utterance = {
  id: string;
  text: string;
  createdAt: string;
  taskId: string | null;
  confidence: number;
  autoAssigned: boolean;
  confirmed: boolean;
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
  engine: "browser" | "grok";
  wizardDone: boolean;
  pauseSec: number;
  compactMode: boolean;
};

export type MapLink = {
  a: string;
  b: string;
  label: string;
};

export type AppState = {
  settings: Settings;
  tasks: Task[];
  utterances: Utterance[];
  protocols: Protocol[];
  mapLinks: MapLink[];
  hiddenPairs: string[];
};
