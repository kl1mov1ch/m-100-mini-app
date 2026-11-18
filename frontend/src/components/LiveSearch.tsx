import { Alert, Empty } from 'antd';
import { Input } from './Input';
import { Button } from './Button';
import { Check, FileSpreadsheet, LoaderCircle, Plus } from 'lucide-react';
import { TelegramIcon } from './TelegramIcon';
import { ProjectMatchHint } from './ProjectMatchHint';
import { useEffect, useMemo, useRef, useState } from 'react';
import { request } from '../lib/api';
import { Money, shortName, unit } from '../lib/format';
import { estimateStatus } from '../lib/position-volume';
import { rankedSearch } from '../lib/search';
import type { Position, ProjectMatch, SearchResult } from '../types';
const pageSize = 60;

export function LiveSearch({
	project,
	positions,
	onSelect,
	onProjectMatch,
	selected = [],
}: {
	project: string;
	positions: Position[];
	onSelect: (id: string) => void;
	onProjectMatch?: (id: string) => void;
	selected?: string[];
}) {
	const [q, setQ] = useState(''),
		[result, setResult] = useState<SearchResult | null>(null),
		[loading, setLoading] = useState(false),
		[error, setError] = useState('');
	const seq = useRef(0);
	const searchContainer = useRef<HTMLDivElement>(null);
	const [controlsHidden, setControlsHidden] = useState(false);
	const [limit, setLimit] = useState(pageSize);
	const searchRequest = useRef<AbortController | null>(null);
	const [projectMatch, setProjectMatch] = useState<ProjectMatch>();
	useEffect(() => {
		const scrollContainer = searchContainer.current?.closest('.ant-modal-body');
		if (!scrollContainer) return;
		let previousScroll = scrollContainer.scrollTop;
		let animationFrame = 0;
		const updateControls = () => {
			cancelAnimationFrame(animationFrame);
			animationFrame = requestAnimationFrame(() => {
				const currentScroll = scrollContainer.scrollTop;
				const distance = currentScroll - previousScroll;
				if (
					searchContainer.current?.contains(document.activeElement) ||
					currentScroll < 24 ||
					distance < -3
				)
					setControlsHidden(false);
				else if (distance > 6) setControlsHidden(true);
				previousScroll = currentScroll;
			});
		};
		scrollContainer.addEventListener('scroll', updateControls, {
			passive: true,
		});
		return () => {
			scrollContainer.removeEventListener('scroll', updateControls);
			cancelAnimationFrame(animationFrame);
		};
	}, []);
	const { local, approximate } = useMemo(() => {
		const ranked = rankedSearch(positions, q, (p) =>
			[p.name, p.section, p.unit, p.source_sheet].join(' '),
		);
		const matches = ranked.filter(({ score }) => score >= 4);
		return {
			local: (matches.length ? matches : ranked).map(({ item: p }) => ({ p, reason: '' })),
			approximate: !!q.trim() && (ranked[0]?.score ?? 0) < 9,
		};
	}, [positions, q]);
	const map = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);
	const selectedIds = useMemo(() => new Set(selected), [selected]);
	const suggestions = result
		? result.suggestions.flatMap(({ item_id, reason }) => {
				const p = map.get(item_id);
				return p ? [{ p, reason }] : [];
			})
		: [];
	const options = suggestions.length ? suggestions : local;
	const match = result ? result.project_match : projectMatch;
	useEffect(() => () => searchRequest.current?.abort(), [project]);
	useEffect(() => {
		const query = q.trim();
		if (query.length < 3 || !onProjectMatch || (!approximate && positions.length)) return;
		const controller = new AbortController();
		const timer = window.setTimeout(() => {
			void request<SearchResult>(
				'/search',
				{ text: query, local_only: true },
				project,
				controller.signal,
			)
				.then((response) => {
					if (!controller.signal.aborted) setProjectMatch(response.project_match);
				})
				.catch(() => {});
		}, 450);
		return () => {
			window.clearTimeout(timer);
			controller.abort();
		};
	}, [project, q, approximate, positions.length, Boolean(onProjectMatch)]);
	const searchByMeaning = async () => {
		const id = ++seq.current;
		const controller = new AbortController();
		searchRequest.current = controller;
		setLoading(true);
		setError('');
		try {
			const response = await request<SearchResult>(
				'/search',
				{ text: q.trim() },
				project,
				controller.signal,
			);
			if (id === seq.current && !controller.signal.aborted) setResult(response);
		} catch (failure) {
			if (id === seq.current && !controller.signal.aborted) setError((failure as Error).message);
		} finally {
			if (id === seq.current && !controller.signal.aborted) setLoading(false);
		}
	};
	return (
		<div className="live-search" ref={searchContainer}>
			<div className={'live-search-controls ' + (controlsHidden ? 'is-hidden' : '')}>
				<div className="search-field">
					<TelegramIcon name="search" size={20} />
					<Input
						value={q}
						allowClear
						onChange={(event) => {
							if (event.target.value === q) return;
							seq.current += 1;
							searchRequest.current?.abort();
							setLoading(false);
							setError('');
							setLimit(pageSize);
							setResult(null);
							setProjectMatch(undefined);
							setQ(event.target.value);
						}}
						placeholder="Работа, материал, размер…"
						aria-label="Поиск работ"
					/>
					{loading && <LoaderCircle size={18} className="spinning" />}
				</div>
				<div className="search-meta">
					<span>
						{q
							? result?.engine === 'llm'
								? 'Подобрано по смыслу'
								: approximate
									? 'Похожие позиции для проверки'
									: 'Варианты из вашей таблицы'
							: `${positions.length} работ в смете`}
					</span>
					{q && <span>{loading ? 'Уточняем…' : `${options.length} вариантов`}</span>}
				</div>
			</div>
			{error && <Alert type="warning" message={error} />}
			{match && onProjectMatch && (
				<ProjectMatchHint
					match={match}
					onSwitch={onProjectMatch}
					onDismiss={() => {
						setProjectMatch(undefined);
						if (result) setResult({ ...result, project_match: undefined });
					}}
				/>
			)}
			{q.trim().length > 2 && !result && positions.length > 0 && (
				<Button type="text" loading={loading} onClick={() => void searchByMeaning()}>
					Поиск по смыслу
				</Button>
			)}
			<div className="search-options">
				{options.slice(0, limit).map(({ p, reason }) => (
					<button
						className="search-option"
						key={p.id}
						onClick={() => onSelect(p.id)}
						disabled={selectedIds.has(p.id)}
					>
						<span className="option-icon">
							<FileSpreadsheet size={18} />
						</span>
						<span className="option-content">
							<b>{shortName(p)}</b>
							<span className="option-full">{p.name !== shortName(p) ? p.name : p.section}</span>
							<span className="option-meta">
								<span>
									<strong>{estimateStatus(p.bitrix || p, p.unit)}</strong>
								</span>
								<span>
									<Money value={p.rate} /> / {unit(p.unit)}
								</span>
							</span>
							{reason && result?.engine === 'llm' && (
								<small className="semantic-reason">{reason}</small>
							)}
						</span>
						<span className="option-add">
							{selectedIds.has(p.id) ? <Check size={17} /> : <Plus size={19} />}
						</span>
					</button>
				))}
			</div>
			{options.length > limit && (
				<Button block onClick={() => setLimit((count) => count + pageSize)}>
					Показать ещё
				</Button>
			)}
			{!options.length && !loading && <Empty description="Загрузите смету объекта" />}
		</div>
	);
}
