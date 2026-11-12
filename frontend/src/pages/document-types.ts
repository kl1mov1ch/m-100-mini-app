export type DocumentSource = {
	name: string;
	category: string;
	quantity: string | number | null;
	unit: string | null;
	page: number;
	quote: string;
	notes: string;
	question: string;
	original_quantity: string | number | null;
	original_unit: string | null;
	conversion_factor: string | null;
	highlights?: { left: number; top: number; width: number; height: number }[];
};
export type DocumentGroup = {
	id: string;
	name: string;
	category: string;
	unit: string | null;
	quantity: string | number | null;
	proposed_quantity: string | number | null;
	rate: string | number | null;
	notes: string;
	confirmed: boolean;
	issues: string[];
	sources: DocumentSource[];
	amount?: number;
};
export type DocumentJob = {
	id: string;
	name: string;
	status: string;
	pages: number;
	processed: number;
	updated_at: string;
	payload: {
		query?: string;
		questions?: string[];
		notice?: string;
		groups?: DocumentGroup[];
		summary?: { positions: number; confirmed: number; amount: number; unresolved: number };
		coverage?: { complete: boolean; drawings: number[]; low_ocr?: number[]; questions?: number };
		analysis_done?: number;
		analysis_total?: number;
		acknowledge_scope?: boolean;
	};
};
