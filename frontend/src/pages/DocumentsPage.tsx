import { App, Button, Empty, Input, Spin, Upload } from 'antd';
import {
	ChevronDown,
	ChevronRight,
	FilePlus2,
	FileText,
	LoaderCircle,
	RefreshCw,
	X,
} from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { DocumentResultsPage } from './DocumentResultsPage';
import { DocumentProgress, documentActive } from './DocumentProgress';
import type { DocumentJob } from './document-types';
import './documents.css';

type PendingFile = { uid: string; file: File; state: 'pending' | 'uploading' | 'cancelling' };
type Transfer = { job?: string; controller: AbortController; cancelled: boolean };
const labels: Record<string, string> = {
	uploading: 'Загрузка файла',
	queued: 'Ожидает запуска',
	extracting: 'Читаем страницы',
	needs_ocr: 'Нужна проверка OCR',
	ai_queued: 'Передаём в ИИ',
	analysing: 'Собираем данные',
	needs_ai: 'Подключите ИИ',
	needs_budget: 'Продолжите обработку',
	needs_review: 'Можно проверить данные',
	ready: 'Готово к созданию таблицы',
	failed: 'Нужна проверка',
	text_ready: 'Текст извлечён',
	draft: 'Черновик',
	publishing: 'Записываем таблицу',
	publish_retry: 'Проверьте запись',
	published: 'Объект создан',
};
export function DocumentsPage({ workspace }: { workspace: WorkspaceView }) {
	const { message, modal } = App.useApp();
	const [jobs, setJobs] = useState<DocumentJob[]>([]),
		[selected, setSelected] = useState<DocumentJob | null>(null),
		[query, setQuery] = useState(''),
		[files, setFiles] = useState<PendingFile[]>([]),
		[loading, setLoading] = useState(false),
		[uploading, setUploading] = useState(false),
		[composerOpen, setComposerOpen] = useState(true),
		[error, setError] = useState(''),
		[deleting, setDeleting] = useState<string[]>([]);
	const transfers = useRef(new Map<string, Transfer>()),
		removed = useRef(new Set<string>()),
		loadingList = useRef(false);
	useEffect(() => {
		setComposerOpen(!selected);
	}, [selected?.id]);
	const load = async () => {
		if (loadingList.current) return;
		loadingList.current = true;
		try {
			const data = await request<DocumentJob[]>('/documents');
			setJobs(data.filter((job) => !removed.current.has(job.id)));
			setError('');
		} catch (failure) {
			setError((failure as Error).message);
		} finally {
			loadingList.current = false;
			setLoading(false);
		}
	};
	const processing =
		jobs.some((job) => documentActive(job.status)) ||
		(!!selected && documentActive(selected.status));
	const selectedVersion = jobs.find((job) => job.id === selected?.id)?.updated_at;
	useEffect(() => {
		setLoading(true);
		void load();
		const timer = setInterval(
			() => {
				if (!document.hidden) void load();
			},
			processing ? 2000 : 10000,
		);
		const onVisible = () => {
			if (!document.hidden) void load();
		};
		document.addEventListener('visibilitychange', onVisible);
		return () => {
			clearInterval(timer);
			document.removeEventListener('visibilitychange', onVisible);
		};
	}, [workspace.session.user.telegram_id, processing]);
	useEffect(() => {
		if (!selected) return;
		const brief = jobs.find((job) => job.id === selected.id);
		if (!brief || brief.updated_at === selected.updated_at) return;
		const controller = new AbortController();
		void request<DocumentJob>('/documents/' + selected.id, undefined, undefined, controller.signal)
			.then((job) => {
				if (!removed.current.has(job.id))
					setSelected((current) => (current?.id === job.id ? job : current));
			})
			.catch((failure) => {
				if (!controller.signal.aborted && !removed.current.has(selected.id))
					setError(failure.message);
			});
		return () => controller.abort();
	}, [selectedVersion, selected?.id, selected?.updated_at]);
	const add = (file: File) => {
		setComposerOpen(true);
		if (!file.name.toLowerCase().endsWith('.pdf') || file.size > 50 * 1024 * 1024) {
			message.error('Выберите PDF до 50 МБ');
			return false;
		}
		const uid = crypto.randomUUID();
		transfers.current.set(uid, { controller: new AbortController(), cancelled: false });
		setFiles((current) => [...current, { uid, file, state: 'pending' }]);
		return false;
	};
	const cancel = async (file: PendingFile) => {
		const transfer = transfers.current.get(file.uid);
		if (!transfer) return;
		transfer.cancelled = true;
		if (file.state === 'pending') {
			setFiles((current) => current.filter((item) => item.uid !== file.uid));
			return;
		}
		setFiles((current) =>
			current.map((item) => (item.uid === file.uid ? { ...item, state: 'cancelling' } : item)),
		);
		if (transfer.job) {
			try {
				await request('/documents/' + transfer.job + '/delete', {});
				removed.current.add(transfer.job);
				transfer.controller.abort();
				setFiles((current) => current.filter((item) => item.uid !== file.uid));
				await load();
			} catch (failure) {
				setError('Не удалось отменить загрузку: ' + (failure as Error).message);
			}
		}
	};
	const start = async () => {
		setUploading(true);
		setError('');
		for (const item of files.filter((file) => file.state === 'pending')) {
			const transfer = transfers.current.get(item.uid);
			if (!transfer || transfer.cancelled) continue;
			setFiles((current) =>
				current.map((file) => (file.uid === item.uid ? { ...file, state: 'uploading' } : file)),
			);
			try {
				const reserved = await request<DocumentJob>('/documents/reserve', {
					name: item.file.name,
					query: query.trim(),
				});
				transfer.job = reserved.id;
				if (transfer.cancelled) {
					await request('/documents/' + reserved.id + '/delete', {});
					removed.current.add(reserved.id);
					continue;
				}
				const form = new FormData();
				form.append('file', item.file);
				const job = await request<DocumentJob>(
					'/documents/' + reserved.id + '/file',
					form,
					undefined,
					transfer.controller.signal,
				);
				if (!transfer.cancelled) setSelected(job);
			} catch (failure) {
				if (!transfer.cancelled) setError((failure as Error).message);
				if (transfer.job) {
					try {
						await request('/documents/' + transfer.job + '/delete', {});
						removed.current.add(transfer.job);
					} catch {
						if (!transfer.cancelled)
							setError('Загрузка не завершена. Удалите её из списка документов.');
					}
				}
			} finally {
				setFiles((current) => current.filter((file) => file.uid !== item.uid));
				await load();
			}
		}
		setUploading(false);
	};
	const open = async (id: string) => {
		try {
			setSelected(await request<DocumentJob>('/documents/' + id));
		} catch (failure) {
			message.error((failure as Error).message);
		}
	};
	const remove = async (job: DocumentJob) => {
		setDeleting((current) => [...current, job.id]);
		try {
			await request('/documents/' + job.id + '/delete', {});
			removed.current.add(job.id);
			setJobs((current) => current.filter((item) => item.id !== job.id));
			setSelected((current) => (current?.id === job.id ? null : current));
		} catch (failure) {
			message.error((failure as Error).message);
		} finally {
			setDeleting((current) => current.filter((id) => id !== job.id));
		}
	};
	const askRemove = (job: DocumentJob) => {
		if (['uploading', 'queued', 'extracting', 'ai_queued', 'analysing'].includes(job.status)) {
			void remove(job);
			return;
		}
		modal.confirm({
			className: 'action-confirm-sheet',
			icon: null,
			title: 'Удалить документ?',
			content: (
				<div className="action-confirm-content">
					<strong>{job.name}</strong>
					<p>
						Файл и выборка будут удалены.
						{job.payload.publication?.phase === 'published'
							? ' Созданный объект и таблица Битрикс24 останутся.'
							: ''}
					</p>
				</div>
			),
			okText: 'Удалить',
			cancelText: 'Оставить',
			okButtonProps: { danger: true },
			onOk: () => remove(job),
		});
	};
	const resume = async () => {
		if (!selected) return;
		try {
			const action = ['needs_ai', 'needs_budget', 'text_ready'].includes(selected.status)
				? 'analyse'
				: 'retry';
			setSelected(await request<DocumentJob>('/documents/' + selected.id + '/' + action, {}));
			await load();
		} catch (failure) {
			message.error((failure as Error).message);
		}
	};
	const visibleJobs = jobs.filter(
		(job) => !files.some((file) => transfers.current.get(file.uid)?.job === job.id),
	);
	return (
		<div className="document-page document-workspace">
			<div className="page-title">
				<div>
					<h1>Документы</h1>
					<small className="page-context">PDF → данные → таблица объекта</small>
				</div>
				<Button
					type="text"
					aria-label="Обновить документы"
					icon={<RefreshCw size={18} />}
					onClick={() => void load()}
				/>
			</div>
			<section className="document-upload">
				<div className="document-upload-heading">
					<button
						className="document-compose-toggle"
						aria-expanded={composerOpen}
						onClick={() => setComposerOpen((current) => !current)}
					>
						{composerOpen ? 'Что найти в проекте?' : 'Новая выборка'}
						<ChevronDown size={14} />
					</button>
					<Upload accept=".pdf" multiple beforeUpload={add} showUploadList={false}>
						<Button type="text" icon={<FilePlus2 size={17} />}>
							Добавить PDF
						</Button>
					</Upload>
				</div>
				<div hidden={!composerOpen && !files.length}>
					<Input.TextArea
						value={query}
						onChange={(event) => setQuery(event.target.value)}
						maxLength={2000}
						autoSize={{ minRows: 2, maxRows: 4 }}
						aria-label="Что найти в PDF"
						placeholder="Например: только вентиляция. Пустое поле — все работы."
					/>
					{!!files.length && (
						<div className="document-pending-files">
							{files.map((file) => (
								<div key={file.uid}>
									<FileText size={17} />
									<span>
										<strong>{file.file.name}</strong>
										<small>
											{file.state === 'pending'
												? (file.file.size / 1024 / 1024).toFixed(1) + ' МБ'
												: file.state === 'cancelling'
													? 'Отменяем…'
													: 'Загружаем…'}
										</small>
									</span>
									<Button
										type="text"
										aria-label={'Убрать ' + file.file.name}
										loading={file.state === 'cancelling'}
										icon={<X size={17} />}
										onClick={() => void cancel(file)}
									/>
								</div>
							))}
						</div>
					)}
					<div className="document-upload-actions">
						<small>PDF до 50 МБ · все страницы</small>
						{!!files.some((file) => file.state === 'pending') && (
							<Button type="primary" loading={uploading} onClick={() => void start()}>
								Собрать данные
							</Button>
						)}
					</div>
				</div>
			</section>
			{error && (
				<p className="document-notice" role="alert">
					{error}
				</p>
			)}
			<Spin spinning={loading}>
				<div className="document-jobs">
					{visibleJobs.map((job) => (
						<div
							className={'document-job' + (selected?.id === job.id ? ' selected' : '')}
							key={job.id}
						>
							<button
								className="document-job-open"
								onClick={() => (selected?.id === job.id ? setSelected(null) : void open(job.id))}
							>
								<span className="document-file-icon">
									{documentActive(job.status) ? (
										<LoaderCircle size={19} className="spinning" />
									) : (
										<FileText size={19} />
									)}
								</span>
								<span className="document-job-label">
									<strong>{job.name}</strong>
									<small>
										{labels[job.status] || job.status}
										{job.pages ? ` · ${job.processed}/${job.pages} стр.` : ''}
									</small>
								</span>
								{selected?.id === job.id ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
							</button>
							<Button
								type="text"
								aria-label={'Удалить ' + job.name}
								loading={deleting.includes(job.id)}
								disabled={job.status === 'publishing'}
								icon={<X size={17} />}
								onClick={() => askRemove(job)}
							/>
						</div>
					))}
				</div>
			</Spin>
			{!jobs.length && !files.length && !loading && !error && (
				<Empty
					image={Empty.PRESENTED_IMAGE_SIMPLE}
					description="Добавьте PDF — найденные работы появятся здесь"
				/>
			)}
			{selected &&
				(documentActive(selected.status) ||
					!selected.payload.groups?.length ||
					['failed', 'needs_ai', 'needs_budget', 'needs_ocr', 'text_ready'].includes(
						selected.status,
					)) && <DocumentProgress job={selected} resume={() => void resume()} />}

			{selected && !!selected.payload.groups?.length && (
				<DocumentResultsPage
					key={selected.id}
					embedded
					job={selected}
					back={() => setSelected(null)}
					refresh={(job) => {
						setSelected(job);
						void load();
					}}
					openObject={async (id) => {
						await workspace.loadSession();
						workspace.selectObject(id);
					}}
				/>
			)}
		</div>
	);
}
