import { Button, Progress } from 'antd';
import { Check, LoaderCircle, TriangleAlert } from 'lucide-react';
import type { DocumentJob } from './document-types';

export const documentActive = (status: string) =>
	['uploading', 'queued', 'extracting', 'ai_queued', 'analysing'].includes(status);

export function DocumentProgress({ job, resume }: { job: DocumentJob; resume: () => void }) {
	const active = documentActive(job.status);
	const progress = job.payload.progress;
	const stage = progress?.stage;
	const page = progress?.page;
	const paused = ['needs_ocr', 'failed', 'needs_ai', 'needs_budget', 'text_ready'].includes(
		job.status,
	);
	const title =
		stage === 'verifying' && active
			? 'ИИ сверяет ячейки с PDF'
			: stage === 'grouping' && active
				? 'Объединяем одинаковые работы'
				: stage === 'converting' && active
					? `Преобразуем в текст · страница ${page || '…'}`
					: stage === 'indexing' && active
						? 'Ищем ведомости и спецификации'
						: job.status === 'uploading'
							? 'Получаем файл'
							: job.status === 'queued'
								? job.processed
									? 'Продолжаем чтение'
									: 'Файл готов к обработке'
								: job.status === 'ai_queued'
									? 'Передаём страницы ИИ'
									: job.status === 'analysing'
										? `ИИ обрабатывает страницу ${page || '…'}`
										: job.status === 'extracting'
											? `${stage === 'rendering' ? 'Готовим' : stage === 'ocr' ? 'Распознаём' : stage === 'table_ocr' ? 'Читаем таблицы на' : 'Читаем'} страницу ${page || job.processed + 1}`
											: job.status === 'needs_ai'
												? 'Нужно подключить ИИ'
												: job.status === 'needs_budget'
													? 'Достигнут лимит обработки'
													: job.status === 'needs_ocr'
														? 'Нужно распознавание текста'
														: job.status === 'failed'
															? 'Обработка остановлена'
															: 'Страницы прочитаны';
	const size = job.payload.file_bytes
		? `${(job.payload.file_bytes / 1048576).toLocaleString('ru', { maximumFractionDigits: 1 })} МБ`
		: '';
	const done = job.payload.analysis_done || 0;
	const total = job.payload.analysis_total || 0;
	const percent = Math.round((job.processed / Math.max(1, job.pages)) * 100);
	return (
		<section className="document-analysis document-live-progress" role="status" aria-live="polite">
			<div className="document-section-title">
				<h2>
					{active ? (
						<LoaderCircle size={17} className="spinning" />
					) : paused ? (
						<TriangleAlert size={17} />
					) : (
						<Check size={17} />
					)}
					{title}
				</h2>
			</div>
			<div className="document-progress-metadata">
				{job.pages ? `${job.pages} стр.` : 'Определяем число страниц'}
				{size && ` · ${size}`}
			</div>
			<div className="document-progress-counts">
				<span>
					{stage === 'verifying'
						? 'Проверено строк'
						: stage === 'converting'
							? 'Преобразовано страниц'
							: stage === 'indexing'
								? 'Проверено страниц'
								: job.payload.selection_complete
									? 'Обработано страниц файла'
									: 'Прочитано страниц'}
				</span>
				<strong>
					{stage === 'verifying'
						? done
						: stage === 'converting'
							? job.payload.conversion_done || 0
							: stage === 'indexing'
								? job.payload.index_done || 0
								: job.processed}{' '}
					/ {(stage === 'verifying' ? total : job.pages) || '…'}
				</strong>
			</div>
			{job.pages > 0 && (
				<Progress
					size="small"
					percent={
						stage === 'verifying'
							? Math.round((done / Math.max(1, total)) * 100)
							: stage === 'converting'
								? Math.round(((job.payload.conversion_done || 0) / Math.max(1, job.pages)) * 100)
								: stage === 'indexing'
									? Math.round(((job.payload.index_done || 0) / job.pages) * 100)
									: percent
					}
					showInfo={false}
					status={
						active && (stage === 'verifying' ? done < total : job.processed < job.pages)
							? 'active'
							: 'normal'
					}
				/>
			)}
			{stage !== 'verifying' && (total > 0 || ['ai_queued', 'analysing'].includes(job.status)) && (
				<div className="document-progress-counts">
					<span>Обработано видов работ</span>
					<strong>
						{done} / {total || '…'}
					</strong>
				</div>
			)}
			{job.payload.selection_complete && (
				<small className="document-progress-metadata">
					Отобрано листов с данными: {job.payload.selected_specifications?.length || 0} · чертежи не
					разбираются
				</small>
			)}
			{!active && job.payload.groups?.length ? (
				<div className="document-progress-counts">
					<span>Найдено позиций</span>
					<strong>{job.payload.groups.length}</strong>
				</div>
			) : null}
			{!active && job.payload.notice && (
				<p className="document-progress-notice">{job.payload.notice}</p>
			)}
			{paused && (
				<Button onClick={resume}>
					{job.status === 'failed' ? 'Повторить обработку' : 'Продолжить обработку'}
				</Button>
			)}
			{job.status === 'needs_review' && !job.payload.groups?.length && (
				<Button onClick={resume}>Пересобрать выборку</Button>
			)}
		</section>
	);
}
