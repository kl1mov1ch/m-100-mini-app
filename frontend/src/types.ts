export type User = {
	telegram_id: string;
	name: string;
	role: string;
	enabled: number;
	avatar_url?: string;
	username?: string;
	projects?: number;
};
export type Project = {
	id: string;
	name: string;
	owner_id: string;
	owner_name: string;
	positions: number;
	today_amount: number;
	today_crew: number | null;
	today_per_person: number;
	today_positions: number;
	today_confirmed: boolean;
	total_amount: number;
	pending: number;
	connected: boolean;
	source: string;
	last_change: string | null;
	work_dates?: string[];
	table?: {
		name: string;
		read_connected: boolean;
		write_connected: boolean;
		pending_review: boolean;
		last_import: string;
	};
};
export type Position = {
	id: string;
	name: string;
	section: string;
	unit: string;
	planned: number;
	rate: number;
	completed: number;
	remaining: number;
	source_row: number;
	source_sheet?: string;
};
export type Line = {
	item_id: string | null;
	quantity: number | null;
	raw?: string;
	reason?: string;
	candidates?: string[];
};
export type Payroll = {
	amount: number;
	crew_count: number;
	per_person: number;
	extra_people: number;
	extra_per_person: number;
};
export type Report = {
	date: string;
	revision: number;
	text: string;
	sync_status: string;
	sync_error: string;
	crew_count: number;
	lines: Line[];
	payroll: Payroll;
	changed?: boolean;
};
export type HistoryRow = Payroll & {
	date: string;
	positions: number;
	revision: number;
	sync_status: string;
	sync_error: string;
	updated_at: string;
};
export type Config = {
	today: string;
	mode: string;
	llm: boolean;
	source: string;
	source_name: string;
	public_url: string;
	file_id: number;
	has_webhook: boolean;
	last_import: string;
	pending_import: boolean;
	detail_url?: string;
	connection_check?: {
		reachable: boolean;
		structure_valid?: boolean;
		checked_at: string;
		name?: string;
		positions?: number;
		issues: ImportWarning[];
		write_configured: boolean;
		message: string;
	};
};
export type Data = {
	project?: { id: string; name: string };
	positions: Position[];
	history: HistoryRow[];
	config: Config;
	report: Report;
};
export type Session = {
	user: User;
	projects: Project[];
	mode: string;
	today: string;
	selected_date: string;
	ai_connected: boolean;
	can_switch_role: boolean;
	view_mode: string;
};
export type Suggestion = { item_id: string; reason: string };
export type SearchResult = {
	suggestions: Suggestion[];
	engine: string;
	needs_ai: boolean;
	notice: string;
};
export type Change = {
	id: number;
	date: string;
	created_at: string;
	payload: {
		actor_name: string;
		table_changes?: {
			sheet: string;
			cell: string;
			before?: string | number | null;
			after: string | number | null;
		}[];
		saved_to_source?: boolean;
		changes?: {
			lines: { name: string; unit: string; before: number; after: number }[];
			crew_before: number;
			crew_after: number;
		};
	};
};
export type ImportSheet = {
	name: string;
	columns: { index: number; label: string }[];
	mapping: Record<string, number | null>;
	header_row: number;
	date_row: number;
	rows: number;
};
export type ImportPreview = {
	token: string;
	name: string;
	sheets: ImportSheet[];
	warnings: ImportWarning[];
	positions: Position[];
	source: 'file' | 'bitrix';
};
export type ImportWarning = {
	id: string;
	message: string;
	severity?: string;
	sheet?: string;
	row?: number;
	column?: string;
	cell?: string;
	position_name?: string;
	field?: string;
	value?: string;
	fix?: string;
	confirmation_label?: string;
	duplicates?: { date: string; columns: number[]; cells: string[] }[];
};
export type TableFixPayload = {
	edits?: { sheet: string; cell: string; value: string | number | null }[];
	duplicates?: { sheet: string; date: string; strategy: string; new_date?: string }[];
};
declare global {
	interface Window {
		Telegram?: { WebApp?: import('./lib/telegram-types').TelegramWebApp };
		webkitSpeechRecognition?: new () => SpeechEngine;
		SpeechRecognition?: new () => SpeechEngine;
	}
}
export type SpeechEngine = {
	lang: string;
	start: () => void;
	stop: () => void;
	onresult:
		((e: { results: { [n: number]: { [n: number]: { transcript: string } } } }) => void) | null;
	onerror: (() => void) | null;
	onend: (() => void) | null;
};
