import { Alert, Empty, Input } from 'antd';
import { Check, FileSpreadsheet, LoaderCircle, Plus, Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { request } from '../lib/api';
import { Money, nf, shortName, unit } from '../lib/format';
import type { Position, SearchResult } from '../types';
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
				if (currentScroll < 24 || distance < -3) setControlsHidden(false);
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
	useEffect(() => {
		const id = ++seq.current;
		const controller = new AbortController();
		if (!q.trim()) {
			setResult(null);
			setLoading(false);
			setError('');
			return () => controller.abort();
		}
		setLoading(true);
		setError('');
		const timer = setTimeout(async () => {
			try {
				const local = await request<SearchResult>(
					'/search',
					{ text: q, local_only: true },
					project,
					controller.signal,
				);
				if (id !== seq.current) return;
				setResult(local);
				setLoading(false);
				if (local.needs_ai) {
					setLoading(true);
					await new Promise((resolve) => setTimeout(resolve, 450));
					if (id !== seq.current) return;
					const enriched = await request<SearchResult>(
						'/search',
						{ text: q },
						project,
						controller.signal,
					);
					if (id === seq.current) setResult(enriched);
				}
			} catch (e) {
				if ((e as Error).name !== 'AbortError' && id === seq.current)
					setError((e as Error).message);
			} finally {
				if (id === seq.current) setLoading(false);
			}
		}, 180);
		return () => {
			clearTimeout(timer);
			controller.abort();
		};
	}, [q, project]);
	const map = Object.fromEntries(positions.map((p) => [p.id, p]));
	const options = q.trim()
		? (result?.suggestions || []).flatMap((s) =>
				map[s.item_id] ? [{ p: map[s.item_id], reason: s.reason }] : [],
			)
		: positions.map((p) => ({ p, reason: '' }));
	return (
		<div className="live-search" ref={searchContainer}>
			<div className={'live-search-controls ' + (controlsHidden ? 'is-hidden' : '')}>
				<div className="search-field">
					<Search size={20} />
					<Input
						autoFocus
						value={q}
						allowClear
						onChange={(e) => setQ(e.target.value)}
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
				{options.map(({ p, reason }) => (
					<button
						className="search-option"
						key={p.id}
						onClick={() => onSelect(p.id)}
						disabled={selected.includes(p.id)}
					>
						<span className="option-icon">
							<FileSpreadsheet size={18} />
						</span>
						<span className="option-content">
							<b>{shortName(p)}</b>
							<span className="option-full">{p.name !== shortName(p) ? p.name : p.section}</span>
							<span className="option-meta">
								<span>
									Остаток{' '}
									<strong>
										{nf.format(p.remaining)} {unit(p.unit)}
									</strong>
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
							{selected.includes(p.id) ? <Check size={17} /> : <Plus size={19} />}
						</span>
					</button>
				))}
			</div>
			{!options.length && !loading && (
				<Empty description={positions.length ? 'Совпадений пока нет' : 'Загрузите смету объекта'} />
			)}
		</div>
	);
}
