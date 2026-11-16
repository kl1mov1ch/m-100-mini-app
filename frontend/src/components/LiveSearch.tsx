import { Alert, Button, Empty, Input } from 'antd';
import { Check, FileSpreadsheet, LoaderCircle, Plus, Search } from 'lucide-react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { request } from '../lib/api';
import { Money, shortName, unit } from '../lib/format';
import { estimateStatus } from '../lib/position-volume';
import type { Position, SearchResult } from '../types';
const pageSize = 60;

function searchable(value: string) {
	return value
		.toLowerCase()
		.replaceAll('ё', 'е')
		.replace(/(\d)\s*[×хx]\s*(?=\d)/g, '$1x')
		.replace(/(\d),(?=\d)/g, '$1.')
		.replace(/[ø⌀]\s*|(^|\s)[dд]\s*(?=\d)/g, '$1д')
		.replace(/[²³]/g, (value) => (value === '²' ? '2' : '3'));
}
const queryParts = (value: string) => searchable(value).match(/[\p{L}\p{N}]+(?:\.\d+)?/gu) || [];

export function LiveSearch({
	project,
	positions,
	onSelect,
	selected = [],
}: {
	project: string;
	positions: Position[];
	onSelect: (id: string) => void;
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
	const searchRequest = useRef<AbortController>(null);
	useEffect(() => {
		const scrollContainer = searchContainer.current?.closest('.ant-drawer-body');
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
	const index = useMemo(
		() =>
			positions.map((p) => {
				const name = searchable(p.name);
				const full = searchable(
					[p.name, p.section, p.unit, p.source_sheet].filter(Boolean).join(' '),
				);
				return {
					p,
					name,
					full,
					numbers: new Set(full.match(/\d+(?:\.\d+)?/g) || []),
					terms: new Set(queryParts(full)),
				};
			}),
		[positions],
	);
	const local = useMemo(() => {
		const terms = queryParts(q);
		if (!terms.length) return index;
		const matches = index.filter(({ full, numbers, terms: candidateTerms }) =>
			terms.every((term) =>
				/^\d+(?:\.\d+)?$/.test(term)
					? numbers.has(term)
					: /\d/.test(term)
						? candidateTerms.has(term)
						: full.includes(term),
			),
		);
		return matches.sort(
			(left, right) =>
				Number(terms.every((term) => right.name.includes(term))) -
				Number(terms.every((term) => left.name.includes(term))),
		);
	}, [index, q]);
	const map = useMemo(() => new Map(positions.map((p) => [p.id, p])), [positions]);
	const selectedIds = useMemo(() => new Set(selected), [selected]);
	const options = result
		? result.suggestions.flatMap(({ item_id, reason }) => {
				const p = map.get(item_id);
				return p ? [{ p, reason }] : [];
			})
		: local.map(({ p }) => ({ p, reason: '' }));
	useEffect(() => () => searchRequest.current?.abort(), [project]);
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
					<Search size={20} />
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
								: 'Варианты из вашей таблицы'
							: `${positions.length} работ в смете`}
					</span>
					{q && <span>{loading ? 'Уточняем…' : `${options.length} вариантов`}</span>}
				</div>
			</div>
			{error && <Alert type="warning" message={error} />}
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
			{!options.length && !loading && (
				<Empty
					description={positions.length ? 'Совпадений в смете нет' : 'Загрузите смету объекта'}
				>
					{positions.length > 0 && q.trim().length > 2 && !result && (
						<Button onClick={() => void searchByMeaning()}>Поиск по смыслу</Button>
					)}
				</Empty>
			)}
		</div>
	);
}
