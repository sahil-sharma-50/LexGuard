import type { LiveReadResult } from "../../lib/types"

/** Panel state: a live read result, or the first render before any read. */
export type PanelData<T> = LiveReadResult<T> | { status: "loading" }
