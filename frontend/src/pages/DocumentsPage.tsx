import { App, Button, Empty, Modal, Progress, Select, Spin, Tag, Upload } from 'antd';
import { Bot, ChevronRight, Download, FileText, RefreshCw, UploadCloud } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { downloadReport } from '../lib/report-download';
import './documents.css';

type Work = {
	name: string;
	category: string;
	quantity: number | null;
	unit: string | null;
	page: number;
	quote: string;
	notes: string;
	question: string;
};
type Job = {
	id: string;
	name: string;
	status: string;
	pages: number;
	processed: number;
	payload: {
		notice?: string;
		page_results: { page: number; kind: string; characters: number; excerpt: string }[];
		works: Work[];
		questions: string[];
		analysed_pages?: number[];
	};
};
const labels: Record<string, string> = {
	queued: 'В очереди',
	extracting: 'Чтение страниц',
	needs_ocr: 'Нужен OCR',
	text_ready: 'Текст готов',
	ai_queued: 'В очереди ИИ',
	analysing: 'ИИ разбирает',
	needs_ai: 'Нужен ключ ИИ',
	draft: 'Черновик готов',
	failed: 'Нужна проверка',
};

export function DocumentsPage({ workspace }: { workspace: WorkspaceView }) {
	const [jobs, setJobs] = useState<Job[]>([]),
		[selected, setSelected] = useState<string>(),
		[loading, setLoading] = useState(false),
		[uploading, setUploading] = useState(false),
		[busy, setBusy] = useState(false),
		[error, setError] = useState(''),
		[pages, setPages] = useState<number[]>([]),
		[category, setCategory] = useState('Все'),
		[source, setSource] = useState<Work | null>(null);
	const { message } = App.useApp();
	const job = jobs.find((item) => item.id === selected);
	const load = async () => {
		try {
			const data = await request<Job[]>('/documents');
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
		setPages([]);
		setCategory('Все');
	}, [selected]);
	const upload = async (file: File) => {
		setUploading(true);
		try {
			const form = new FormData();
			form.append('file', file);
			const result = await request<Job>('/documents', form);
			setSelected(result.id);
			await load();
			message.success('PDF добавлен в очередь');
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setUploading(false);
		}
		return false;
	};
	const act = async (action: string, body: unknown = {}) => {
		if (!job) return;
		setBusy(true);
		try {
			await request('/documents/' + job.id + '/' + action, body);
			await load();
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setBusy(false);
		}
	};
	const works = job?.payload.works || [];
	const categories = ['Все', ...new Set(works.map((work) => work.category))];
	const readable = job?.payload.page_results.filter((page) => page.kind !== 'needs_ocr') || [];
	const aiAllowed = job && ['text_ready', 'draft', 'needs_ai'].includes(job.status);
	return (
		<>
			<div className="page-title">
				<div>
					<h1>Документы</h1>
					<small className="page-context">Работы из проекта PDF</small>
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
				<div>
					<UploadCloud size={22} />
					<strong>Загрузите проект</strong>
				</div>
				<p>
					Сначала распознаем страницы, затем ИИ предложит работы по категориям. Черновик можно
					скачать в Excel для проверки.
				</p>
				<Upload accept=".pdf" showUploadList={false} beforeUpload={upload} disabled={uploading}>
					<Button type="primary" icon={<UploadCloud size={17} />} loading={uploading}>
						Выбрать PDF
					</Button>
				</Upload>
				<small>До 50 МБ · сканированные и текстовые PDF</small>
			</section>
			{error && (
				<div className="document-notice" role="alert">
					{error}
				</div>
			)}
			<Spin spinning={loading}>
				<div className="document-jobs">
					{jobs.map((item) => (
						<button
							className={'document-job' + (selected === item.id ? ' selected' : '')}
							key={item.id}
							onClick={() => setSelected(item.id)}
						>
							<FileText size={20} />
							<span>
								<strong>{item.name}</strong>
								<small>
									{labels[item.status] || item.status}
									{item.pages > 0 ? ` · ${item.processed}/${item.pages} стр.` : ''}
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
					description="Здесь появятся загруженные проекты"
				/>
			)}
			{job && (
				<section className="document-analysis">
					<div className="document-section-title">
						<h2>Разбор проекта</h2>
						<Tag>{labels[job.status]}</Tag>
					</div>
					<div className="document-agents">
						{[
							{
								name: 'Распознавание',
								done: job.status === 'text_ready' || works.length > 0,
								active: job.status === 'extracting',
							},
							{
								name: 'Разбор ИИ',
								done: job.status === 'draft',
								active: job.status === 'analysing',
							},
							{ name: 'Проверка', done: false, active: job.status === 'draft' },
						].map((agent, index) => (
							<div key={agent.name} className={agent.done ? 'done' : agent.active ? 'active' : ''}>
								<span>{index + 1}</span>
								<small>{agent.name}</small>
							</div>
						))}
					</div>
					{job.pages > 0 && (
						<Progress
							percent={Math.round((job.processed / job.pages) * 100)}
							size="small"
							status={job.status === 'extracting' ? 'active' : 'normal'}
						/>
					)}
					{job.payload.notice && <p className="document-notice">{job.payload.notice}</p>}
					{['needs_ocr', 'failed'].includes(job.status) && (
						<Button loading={busy} onClick={() => void act('retry')}>
							Повторить обработку
						</Button>
					)}
					{aiAllowed && (
						<div className="document-ai-controls">
							<label>
								Страницы для ИИ
								<Select
									mode="multiple"
									maxCount={12}
									placeholder="Выберите до 12 страниц"
									value={pages}
									onChange={setPages}
									options={readable.map((page) => ({
										value: page.page,
										label: `Стр. ${page.page} · ${page.kind === 'specification' ? 'Спецификация' : page.kind === 'drawing' ? 'Чертёж / схема' : 'Описание'}${job.payload.analysed_pages?.includes(page.page) ? ' · разобрана' : ''}`,
									}))}
								/>
							</label>
							<Button
								type="primary"
								icon={<Bot size={17} />}
								loading={busy}
								disabled={!pages.length}
								onClick={() => void act('analyse', { pages })}
							>
								Разобрать выбранные страницы
							</Button>
						</div>
					)}
					{!!works.length && (
						<>
							<div className="document-result-tools">
								<Select
									aria-label="Категория работ из PDF"
									value={category}
									onChange={setCategory}
									options={categories.map((value) => ({ value, label: value }))}
								/>
								<Button
									icon={<Download size={16} />}
									onClick={() =>
										void downloadReport('/documents/' + job.id + '/export.xlsx').catch((failure) =>
											message.error(failure.message),
										)
									}
								>
									Excel
								</Button>
							</div>
							<small className="document-result-note">
								Черновик: расценки и коэффициенты не назначены. Каждая позиция требует проверки.
							</small>
							<div className="document-works">
								{works
									.filter((work) => category === 'Все' || work.category === category)
									.map((work, index) => (
										<button className="document-work" key={index} onClick={() => setSource(work)}>
											<strong>{work.name}</strong>
											<span>
												{work.category} · стр. {work.page}
											</span>
											<b>
												{work.quantity === null
													? 'Объём уточнить'
													: `${work.quantity} ${work.unit || 'единицу уточнить'}`}
											</b>
											{work.notes && <small>{work.notes}</small>}
											<small className="document-question">{work.question}</small>
										</button>
									))}
							</div>
						</>
					)}
					{!!job.payload.questions.length && (
						<details className="document-questions">
							<summary>Что уточнить · {job.payload.questions.length}</summary>
							<ul>
								{job.payload.questions.map((question, index) => (
									<li key={index}>{question}</li>
								))}
							</ul>
						</details>
					)}
				</section>
			)}
			<Modal
				title={source?.name}
				open={!!source}
				footer={<Button onClick={() => setSource(null)}>Понятно</Button>}
				onCancel={() => setSource(null)}
			>
				<div className="document-source">
					<strong>Источник · страница {source?.page}</strong>
					<blockquote>{source?.quote}</blockquote>
					{source?.notes && <p>{source.notes}</p>}
					<p className="document-question">{source?.question}</p>
				</div>
			</Modal>
		</>
	);
}
