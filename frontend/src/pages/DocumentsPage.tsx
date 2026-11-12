import { App, Button, Empty, Input, Progress, Spin, Upload } from 'antd';
import { ArrowRight, ChevronRight, FileText, RefreshCw, UploadCloud } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { DocumentResultsPage } from './DocumentResultsPage';
import type { DocumentJob } from './document-types';
import './documents.css';

const labels: Record<string, string> = {
	queued: 'В очереди',
	extracting: 'Распознавание PDF',
	needs_ocr: 'Нужен OCR',
	ai_queued: 'В очереди ИИ',
	analysing: 'Сбор выборки',
	needs_ai: 'Подключите ИИ',
	needs_budget: 'Нужно продолжить обработку',
	needs_review: 'Выборка готова к проверке',
	ready: 'Проверено и оценено',
	failed: 'Нужна проверка',
	text_ready: 'Текст извлечён',
	draft: 'Черновик',
};
export function DocumentsPage({ workspace }: { workspace: WorkspaceView }) {
	const [jobs, setJobs] = useState<DocumentJob[]>([]),
		[selected, setSelected] = useState<DocumentJob | null>(null),
		[results, setResults] = useState(false),
		[query, setQuery] = useState(''),
		[loading, setLoading] = useState(false),
		[uploading, setUploading] = useState(false),
		[error, setError] = useState('');
	const { message } = App.useApp();
	const load = async () => {
		try {
			const data = await request<DocumentJob[]>('/documents');
			setJobs(data);
			setError('');
		} catch (failure) {
			setError((failure as Error).message);
		} finally {
			setLoading(false);
		}
	};
	useEffect(() => {
		setLoading(true);
		void load();
		const timer = setInterval(() => void load(), 4000);
		return () => clearInterval(timer);
	}, [workspace.session.user.telegram_id]);
	useEffect(() => {
		if (!selected) return;
		const summary = jobs.find((job) => job.id === selected.id);
		if (summary && summary.updated_at !== selected.updated_at)
			void request<DocumentJob>('/documents/' + selected.id)
				.then(setSelected)
				.catch((error) => message.error(error.message));
	}, [jobs, selected?.id]);
	const open = async (id: string) => {
		try {
			setSelected(await request<DocumentJob>('/documents/' + id));
			setResults(false);
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	const upload = async (file: File) => {
		if (query.trim().length < 3) {
			message.info('Напишите, какую выборку собрать');
			return false;
		}
		setUploading(true);
		try {
			const form = new FormData();
			form.append('file', file);
			form.append('query', query.trim());
			const job = await request<DocumentJob>('/documents', form);
			setSelected(job);
			setResults(false);
			await load();
			message.success('Проект принят. Обработка выполняется в фоне.');
		} catch (error) {
			message.error((error as Error).message);
		} finally {
			setUploading(false);
		}
		return false;
	};
	const resume = async () => {
		if (!selected) return;
		try {
			const action = ['needs_ai', 'needs_budget', 'text_ready'].includes(selected.status)
				? 'analyse'
				: 'retry';
			setSelected(await request<DocumentJob>('/documents/' + selected.id + '/' + action, {}));
			await load();
		} catch (error) {
			message.error((error as Error).message);
		}
	};
	if (results && selected)
		return (
			<DocumentResultsPage
				job={selected}
				back={() => setResults(false)}
				refresh={(job) => {
					setSelected(job);
					void load();
				}}
			/>
		);
	return (
		<div className="document-page">
			<div className="page-title">
				<div>
					<h1>Документы</h1>
					<small className="page-context">Выборка работ из PDF-проекта</small>
				</div>
				<Button
					type="text"
					aria-label="Обновить документы"
					icon={<RefreshCw size={19} />}
					loading={loading}
					onClick={() => void load()}
				/>
			</div>
			<section className="document-upload">
				<div className="document-upload-heading">
					<div>
						<strong>Новая выборка</strong>
						<small>Какие работы нужны из проекта?</small>
					</div>
					<span className="document-file-icon">
						<FileText size={21} />
					</span>
				</div>
				<Input.TextArea
					value={query}
					onChange={(event) => setQuery(event.target.value)}
					maxLength={2000}
					autoSize={{ minRows: 2, maxRows: 5 }}
					placeholder="Например: вентиляция — воздуховоды, оборудование и изоляция"
					aria-label="Запрос на выборку из PDF"
				/>
				<div className="document-upload-actions">
					<Upload
						accept=".pdf"
						showUploadList={false}
						beforeUpload={upload}
						disabled={uploading || query.trim().length < 3}
					>
						<Button
							type="primary"
							icon={<UploadCloud size={17} />}
							loading={uploading}
							disabled={query.trim().length < 3}
						>
							Выбрать PDF
						</Button>
					</Upload>
					<small>До 50 МБ · все страницы</small>
				</div>
			</section>
			{error && (
				<p className="document-notice" role="alert">
					{error}
				</p>
			)}
			<Spin spinning={loading}>
				{!!jobs.length && (
					<span className="document-group-label">Мои документы · {jobs.length}</span>
				)}
				<div className="document-jobs">
					{jobs.map((job) => (
						<button
							className={'document-job' + (selected?.id === job.id ? ' selected' : '')}
							key={job.id}
							onClick={() => void open(job.id)}
						>
							<span className="document-file-icon">
								<FileText size={20} />
							</span>
							<span className="document-job-label">
								<strong>{job.name}</strong>
								<small>
									{labels[job.status] || job.status}
									{job.pages ? ` · ${job.processed}/${job.pages} стр.` : ''}
								</small>
							</span>
							<ChevronRight size={17} />
						</button>
					))}
				</div>
			</Spin>
			{!jobs.length && !loading && !error && (
				<Empty
					image={Empty.PRESENTED_IMAGE_SIMPLE}
					description="Загрузите проект и укажите нужные работы"
				/>
			)}
			{selected && (
				<section className="document-analysis">
					<div className="document-section-title">
						<h2>{labels[selected.status]}</h2>
						<small>{selected.pages ? `${selected.processed}/${selected.pages} стр.` : ''}</small>
					</div>
					<p className="page-context">{selected.payload.query}</p>
					{!['needs_review', 'ready', 'draft'].includes(selected.status) && (
						<Progress
							size="small"
							percent={
								selected.status === 'extracting'
									? Math.round((selected.processed / Math.max(1, selected.pages)) * 100)
									: ['queued', 'needs_ocr'].includes(selected.status)
										? 0
										: Math.round(
												((selected.payload.analysis_done || 0) /
													Math.max(1, selected.payload.analysis_total || 1)) *
													100,
											)
							}
							status={['extracting', 'analysing'].includes(selected.status) ? 'active' : 'normal'}
						/>
					)}
					{selected.payload.notice && (
						<details className="document-details">
							<summary>Подробнее об обработке</summary>
							<p>{selected.payload.notice}</p>
						</details>
					)}
					{['needs_ocr', 'failed', 'needs_ai', 'needs_budget', 'text_ready'].includes(
						selected.status,
					) && <Button onClick={() => void resume()}>Продолжить обработку</Button>}
					{!!selected.payload.groups?.length && (
						<Button type="primary" block onClick={() => setResults(true)}>
							Открыть выборку
							<ArrowRight size={17} />
						</Button>
					)}
				</section>
			)}
		</div>
	);
}
