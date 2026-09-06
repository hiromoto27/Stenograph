import type { UtteranceKind } from "./types";

export type KindHit = { kind: UtteranceKind; score: number; cues: string[] };

const NEG = /(?:^|[^\p{L}])не\s+(?:были?\s+)?(?:решили|договорились|утвердили|принято)/iu;
const FUTURE = /нужно\s+решить|надо\s+утвердить|будем\s+решать|ещё\s+не\s+решили/i;

export function detectKind(text: string): UtteranceKind {
  const t = text.toLowerCase();
  if (NEG.test(text) || FUTURE.test(text)) return "speech";
  if (/утвердили|договорились|решили|приняли\s+решение/.test(t)) return "decision";
  if (/риск|опасно|может\s+сорваться/.test(t)) return "risk";
  if (/блокер|заблок|стоп[ -]?фактор/.test(t)) return "blocker";
  return "speech";
}
