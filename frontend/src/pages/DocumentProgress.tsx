import { Button, Progress } from 'antd';
import { Check, LoaderCircle, TriangleAlert } from 'lucide-react';
import type { DocumentJob } from './document-types';

export const documentActive = (status: string) =>
	['uploading', 'queued', 'extracting', 'ai_queued', 'analysing'].includes(status);

export function documentMeter(job: DocumentJob) {
	const { analysis_done, analysis_total, conversion_done, text_complete, progress } = job.payload;
	if (progress?.stage === 'grouping' && analysis_total)
		return Math.min(99, 85 + ((analysis_done || 0) * 14) / analysis_total);
	if (job.status === 'analysing' && analysis_total)
		return Math.min(85, 60 + ((analysis_done || 0) * 25) / analysis_total);
	if (text_complete || job.status === 'ai_queued') return 60;
	if (job.pages) return Math.min(60, ((conversion_done ?? job.processed) * 60) / job.pages);
	return undefined;
}

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
			? page
				? `Сверены строки на стр. ${page}`
				: 'Сверяем ячейки с PDF'
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
	const percent = documentMeter(job);
	const step = stage === 'grouping' ? 2 : ['ai_queued', 'analysing'].includes(job.status) ? 1 : 0;
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
			{active && (
				<ol className="document-stage-list">
					{['Читаем PDF', 'Сверяем строки', 'Собираем смету'].map((label, index) => (
						<li
							key={label}
							data-state={index < step ? 'done' : index === step ? 'current' : 'waiting'}
							aria-current={index === step ? 'step' : undefined}
						>
							{index < step && <Check size={13} />}
							{label}
						</li>
					))}
				</ol>
			)}
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
			{active && percent !== undefined && (
				<Progress size="small" percent={Math.round(percent)} status="active" />
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
					{job.payload.scope_categories?.length
						? `${job.payload.scope_categories.join(' · ')} — листов с нужными строками: ${job.payload.scope_pages?.length || 0}`
						: `Отобрано листов с данными: ${job.payload.selected_specifications?.length || 0}`}
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
