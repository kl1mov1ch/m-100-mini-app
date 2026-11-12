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
	hidden?: boolean;
	bitrix?: { planned: number; rate: number; completed: number; remaining: number } | null;
};
export type PositionHistory = {
	can_delete: boolean;
	events: {
		kind: string;
		date: string;
		created_at: string;
		actor?: string;
		before?: number;
		after?: number;
		values?: { before: Record<string, number | string>; after: Record<string, number | string> };
		work?: string;
	}[];
	days: { date: string; quantity: number; sync_status: string | null }[];
};
export type BitrixRead = {
	status: 'current' | 'review' | 'unavailable';
	checked_at: string;
	updated_at: string | null;
};
export type BitrixReviewIssue = {
	kind: 'cell' | 'layout' | 'planned' | 'rate' | 'remaining' | 'report';
	title: string;
	advice: string;
	sheet?: string | null;
	row?: number | null;
	cell?: string | null;
	position?: string | null;
	date?: string;
	value?: string | null;
	unit?: string;
	local?: number;
	remote?: number;
	suggested?: number;
	planned?: number;
	completed?: number;
	formula?: string | null;
};
export type ObjectSection = 'reports' | 'catalogue' | 'table';
export type CatalogueAction = 'delete' | 'hide' | 'show';
export type ViewMode = 'admin' | 'master';
export type ObjectManagement = {
	reports: number;
	pending: number;
};
export type CatalogueReconciliation = {
	version: string;
	needs_confirmation: boolean;
	notice: string;
	report_count: number;
	report_conflicts: {
		date: string;
		local_positions: number;
		remote_positions: number;
		lines: { item_id: string; name: string; unit: string; local: number; remote: number }[];
	}[];
	rows: {
		previous: Position;
		selected_id: string | null;
		required: boolean;
		changed: boolean;
		method: string;
		reason: string;
	}[];
};
export type ReconciliationConfirmation = {
	position_matches: Record<string, string | null>;
	reconciliation_acknowledged: boolean;
	reconciliation_version: string;
	day_resolutions: Record<string, string>;
};
export type Line = {
	item_id: string | null;
	quantity: number | null;
	raw?: string;
	unit?: string | null;
	reason?: string;
	candidates?: string[];
};
export type ParsedReport = {
	lines: Line[];
	notice: string;
	crew_count: number | null;
	crew_ambiguous: boolean;
	needs_ai: boolean;
	engine: string;
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
	bitrix_read?: BitrixRead | null;
	journal_status?: string;
	journal_note?: string;
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
	view_mode: ViewMode;
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
		action?: string;
		position_name?: string;
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
	reconciliation?: CatalogueReconciliation | null;
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
	ai_tip?: string;
	confirmation_label?: string;
	date?: string;
	affected_rows?: number[];
	duplicates?: { date: string; columns: number[]; cells: string[] }[];
};
export type TableFixPayload = {
	edits?: { sheet: string; cell: string; value: string | number | null }[];
	duplicates?: { sheet: string; date: string; strategy: string; new_date?: string }[];
	daily_columns?: {
		sheet: string;
		column: string;
		date: string;
		strategy: 'zero' | 'remove' | 'restore';
	}[];
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
	continuous: boolean;
	interimResults: boolean;
	start: () => void;
	stop: () => void;
	abort: () => void;
	onresult: ((event: { results: ArrayLike<{ 0: { transcript: string } }> }) => void) | null;
	onerror: ((event: { error: string }) => void) | null;
	onend: (() => void) | null;
};
