import { App, Button, Input, Modal } from 'antd';
import { FileText } from 'lucide-react';
import { useState } from 'react';
import { request } from '../lib/api';
import { downloadReport } from '../lib/report-download';
import { SourcePreview } from './DocumentResultsPage';
import type { DocumentJob } from './document-types';

type Hit = { page: number; line: number; text: string; score: number };
export function DocumentTextSearch({ job }: { job: DocumentJob }) {
	const { message } = App.useApp();
	const [results, setResults] = useState<Hit[]>([]),
		[busy, setBusy] = useState(false),
		[searched, setSearched] = useState(false),
		[opened, setOpened] = useState<Hit | null>(null);
	const search = async (query: string) => {
		if (query.trim().length < 2) {
			setResults([]);
			setSearched(false);
			return;
		}
		setBusy(true);
		try {
			const result = await request<{ results: Hit[] }>(
				`/documents/${job.id}/search?q=${encodeURIComponent(query.trim())}`,
			);
			setResults(result.results);
			setSearched(true);
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setBusy(false);
		}
	};
	return (
		<details className="document-checks document-text-search">
			<summary>Поиск и текст документа</summary>
			<Input.Search
				placeholder="Например: воздуховод 200 или изоляция"
				aria-label="Поиск в исходном документе"
				onSearch={(value) => void search(value)}
				loading={busy}
				allowClear
			/>
			{results.length > 0 && (
				<div className="document-works">
					{results.map((hit) => (
						<button
							className="document-search-hit"
							key={`${hit.page}:${hit.line}`}
							onClick={() => setOpened(hit)}
						>
							<strong>Стр. {hit.page}</strong>
							<span>{hit.text.replace(/^Строка \d+: /, '').replace(/C\d+–C\d+=/g, '')}</span>
						</button>
					))}
				</div>
			)}
			{searched && !results.length && (
				<p className="compact-empty">Совпадений в прочитанном тексте нет</p>
			)}
			{job.payload.text_complete && (
				<Button
					type="text"
					icon={<FileText size={16} />}
					onClick={() =>
						void downloadReport(`/documents/${job.id}/text.md`).catch((error) =>
							message.error(error.message),
						)
					}
				>
					Текст всего документа
				</Button>
			)}
			<Modal
				className="document-work-sheet"
				title={opened ? `Источник · страница ${opened.page}` : ''}
				open={!!opened}
				onCancel={() => setOpened(null)}
				footer={<Button onClick={() => setOpened(null)}>Готово</Button>}
				destroyOnHidden
			>
				{opened && (
					<div className="document-source">
						<p>{opened.text}</p>
						<SourcePreview jobId={job.id} page={opened.page} />
					</div>
				)}
			</Modal>
		</details>
	);
}
