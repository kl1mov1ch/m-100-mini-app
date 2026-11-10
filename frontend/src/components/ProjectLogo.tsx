export function ProjectLogo() {
	return (
		<svg viewBox="0 0 40 40" className="project-logo" role="img" aria-label="Логотип проекта">
			<defs>
				<linearGradient id="project-blue" x1="0" y1="0" x2="1" y2="1">
					<stop stopColor="#4285ff" />
					<stop offset="1" stopColor="#1751d7" />
				</linearGradient>
			</defs>
			<rect width="40" height="40" rx="12" fill="url(#project-blue)" />
			<path
				d="M10 29V14L20 9l10 5v15H10Z"
				fill="none"
				stroke="white"
				strokeWidth="1.8"
				strokeLinejoin="round"
			/>
			<path
				d="M15 17h3m5 0h2m-10 5h3m5 0h2"
				stroke="white"
				strokeWidth="1.7"
				strokeLinecap="round"
			/>
			<path
				d="m24 28 3 3 6-7"
				fill="none"
				stroke="#b9edff"
				strokeWidth="2.5"
				strokeLinecap="round"
				strokeLinejoin="round"
			/>
		</svg>
	);
}
