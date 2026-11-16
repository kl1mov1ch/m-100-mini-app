import { App, Button, Empty, Input, Spin, Upload } from 'antd';
import { ChevronRight, FilePlus2, FileText, LoaderCircle, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import type { WorkspaceView } from '../App';
import { request } from '../lib/api';
import { DocumentResultsPage } from './DocumentResultsPage';
import { DocumentProgress, documentActive, documentMeter } from './DocumentProgress';
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
	uploaded: 'Смета на Диске Битрикс24',
	published: 'Объект создан',
};
export function DocumentsPage({
	workspace,
	visible,
}: {
	workspace: WorkspaceView;
	visible: boolean;
}) {
	const { message, modal } = App.useApp();
	const [jobs, setJobs] = useState<DocumentJob[]>([]),
		[selected, setSelected] = useState<DocumentJob | null>(null),
		[query, setQuery] = useState(''),
		[search, setSearch] = useState(''),
		[files, setFiles] = useState<PendingFile[]>([]),
		[loading, setLoading] = useState(true),
		[uploading, setUploading] = useState(false),
		[error, setError] = useState(''),
		[deleting, setDeleting] = useState<string[]>([]);
	const openRequest = useRef<AbortController | null>(null);
	const transfers = useRef(new Map<string, Transfer>()),
		removed = useRef(new Set<string>()),
		loadingList = useRef(false);
	useEffect(() => {
		workspace.documentBack.current = visible && selected ? () => setSelected(null) : null;
		return () => {
			workspace.documentBack.current = null;
			openRequest.current?.abort();
		};
	}, [selected?.id, visible, workspace.documentBack]);
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
		if (!visible) return;
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
	}, [workspace.session.user.telegram_id, processing, visible]);
	useEffect(() => {
		if (!visible || !selected) return;
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
	}, [selectedVersion, selected?.id, selected?.updated_at, visible]);
	const add = (file: File) => {
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
		const pending = files.filter((file) => file.state === 'pending');
		let next = 0;
		const uploadNext = async () => {
			while (next < pending.length) {
				const item = pending[next++];
				const transfer = transfers.current.get(item.uid);
				if (!transfer || transfer.cancelled) continue;
				setFiles((current) =>
					current.map((file) => (file.uid === item.uid ? { ...file, state: 'uploading' } : file)),
				);
				try {
					const reserved = await request<DocumentJob>('/documents/reserve', {
						name: item.file.name,
						query: query.trim(),
						selection_policy: 'specifications',
						engine: 'docling',
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
					if (!transfer.cancelled) {
						setJobs((current) => [job, ...current.filter((candidate) => candidate.id !== job.id)]);
					}
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
		};
		try {
			await Promise.all([uploadNext(), uploadNext()]);
		} finally {
			setUploading(false);
		}
	};
	const open = async (id: string) => {
		openRequest.current?.abort();
		const controller = new AbortController();
		openRequest.current = controller;
		try {
			const job = await request<DocumentJob>(
				'/documents/' + id,
				undefined,
				undefined,
				controller.signal,
			);
			if (!controller.signal.aborted && !removed.current.has(job.id)) setSelected(job);
		} catch (failure) {
			if (!controller.signal.aborted) message.error((failure as Error).message);
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
	const askCancel = (file: PendingFile) =>
		modal.confirm({
			className: 'action-confirm-sheet',
			icon: null,
			title: 'Убрать файл?',
			content: (
				<div className="action-confirm-content">
					<strong>{file.file.name}</strong>
					<p>Загрузка и обработка будут отменены. Файл и извлечённые данные удалятся.</p>
				</div>
			),
			okText: 'Убрать файл',
			cancelText: 'Оставить',
			okButtonProps: { danger: true },
			onOk: () => cancel(file),
		});
	const resume = async (recheck = false) => {
		if (!selected) return;
		try {
			const action =
				recheck || (selected.status === 'needs_review' && !selected.payload.groups?.length)
					? 'rebuild'
					: ['needs_ai', 'needs_budget', 'text_ready'].includes(selected.status)
						? 'analyse'
						: 'retry';
			setSelected(
				await request<DocumentJob>(
					'/documents/' + selected.id + '/' + action,
					action === 'rebuild' ? { version: selected.updated_at } : {},
				),
			);
			await load();
		} catch (failure) {
			message.error((failure as Error).message);
		}
	};
	const visibleJobs = jobs
		.filter(
			(job) =>
				!files.some((file) => transfers.current.get(file.uid)?.job === job.id) &&
				job.name.toLocaleLowerCase('ru').includes(search.trim().toLocaleLowerCase('ru')),
		)
		.sort(
			(left, right) => Number(documentActive(right.status)) - Number(documentActive(left.status)),
		);
	const tone = (job: DocumentJob) =>
		documentActive(job.status)
			? 'active'
			: ['ready', 'uploaded', 'published'].includes(job.status)
				? 'ready'
				: ['failed', 'needs_ai', 'needs_ocr', 'needs_budget'].includes(job.status)
					? 'blocked'
					: 'review';
	return (
		<div className="document-page document-workspace">
			{!selected ? (
				<>
					<div className="page-title">
						<h1>Документы</h1>
						<Upload accept=".pdf" multiple beforeUpload={add} showUploadList={false}>
							<Button type="primary" icon={<FilePlus2 size={17} />}>
								Добавить PDF
							</Button>
						</Upload>
					</div>
					{!!files.length && (
						<section className="document-upload">
							<label className="document-query">
								Что найти в PDF
								<Input
									value={query}
									onChange={(event) => setQuery(event.target.value)}
									onPressEnter={() => {
										if (!uploading && files.some((file) => file.state === 'pending')) void start();
									}}
									maxLength={2000}
									placeholder="Например, вентиляция"
								/>
							</label>
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
												onClick={() => askCancel(file)}
											/>
										</div>
									))}
								</div>
							)}
							<div className="document-upload-actions">
								<small>PDF до 50 МБ · все страницы</small>
								{!!files.some((file) => file.state === 'pending') && (
									<Button type="primary" loading={uploading} onClick={() => void start()}>
										Подобрать работы
									</Button>
								)}
							</div>
						</section>
					)}
					{error && (
						<p className="document-notice" role="alert">
							{error}
							<Button type="link" onClick={() => void load()}>
								Обновить список
							</Button>
						</p>
					)}
					{(jobs.length > 5 || search) && (
						<Input
							aria-label="Найти документ"
							placeholder="Найти документ"
							allowClear
							value={search}
							onChange={(event) => setSearch(event.target.value)}
						/>
					)}
					{search && !visibleJobs.length && <p className="compact-empty">Документы не найдены</p>}
					<Spin spinning={loading}>
						<div className="document-jobs">
							{visibleJobs.map((job) => (
								<div className="document-job" data-tone={tone(job)} key={job.id}>
									<button className="document-job-open" onClick={() => void open(job.id)}>
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
											{documentActive(job.status) && (
												<progress
													aria-label={labels[job.status]}
													className="document-job-progress"
													max={100}
													value={documentMeter(job)}
												/>
											)}
										</span>
										<ChevronRight size={16} />
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
				</>
			) : (
				<div className="page-title document-detail-heading">
					{!window.Telegram?.WebApp?.initData && (
						<Button type="text" onClick={() => setSelected(null)}>
							Все документы
						</Button>
					)}
					<span title={selected.name}>{selected.name}</span>
				</div>
			)}
			{selected &&
				(documentActive(selected.status) ||
					!selected.payload.groups?.length ||
					['failed', 'needs_ai', 'needs_budget', 'needs_ocr', 'text_ready'].includes(
						selected.status,
					)) && <DocumentProgress job={selected} resume={() => void resume()} />}

			{selected &&
				[
					'needs_review',
					'ready',
					'draft',
					'publishing',
					'publish_retry',
					'uploaded',
					'published',
				].includes(selected.status) &&
				!!selected.payload.groups?.length && (
					<DocumentResultsPage
						key={selected.id}
						embedded
						job={selected}
						back={() => setSelected(null)}
						recheck={
							['needs_review', 'ready', 'draft'].includes(selected.status)
								? () => resume(true)
								: undefined
						}
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
