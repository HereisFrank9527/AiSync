const RELEASE_API_URL = "https://api.github.com/repos/HereisFrank9527/AiSync/releases/latest";
const RELEASES_URL = "https://github.com/HereisFrank9527/AiSync/releases/latest";

export interface UpdateAsset {
  name: string;
  url: string;
  size: number;
  kind: "zip" | "tar" | "other";
}

export interface UpdateInfo {
  currentVersion: string;
  latestVersion: string;
  hasUpdate: boolean;
  releaseName: string;
  releaseUrl: string;
  publishedAt: string | null;
  body: string;
  assets: UpdateAsset[];
  preferredAsset: UpdateAsset | null;
}

interface GitHubReleaseAsset {
  name?: string;
  browser_download_url?: string;
  size?: number;
}

interface GitHubRelease {
  tag_name?: string;
  name?: string;
  html_url?: string;
  published_at?: string;
  body?: string;
  assets?: GitHubReleaseAsset[];
}

export function normalizeVersion(value: string) {
  const trimmed = value.trim();
  const match = trimmed.match(/(?:^|[^0-9A-Za-z])v?(\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?)/i)
    ?? trimmed.match(/^v?(\d+(?:\.\d+)+(?:[-+][0-9A-Za-z.-]+)?)/i);
  return (match?.[1] ?? trimmed.replace(/^v/i, "")).trim();
}

function parseVersion(value: string) {
  const normalized = normalizeVersion(value);
  const [withoutBuild] = normalized.split("+", 1);
  const [core, prerelease = ""] = withoutBuild.split("-", 2);
  const numbers = core.split(".").map((part) => Number(part));
  return {
    numbers: numbers.map((part) => Number.isFinite(part) ? part : 0),
    prerelease: prerelease ? prerelease.split(".") : [],
  };
}

function comparePrerelease(left: string[], right: string[]) {
  if (!left.length && !right.length) return 0;
  if (!left.length) return 1;
  if (!right.length) return -1;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const rawLeft = left[index];
    const rawRight = right[index];
    if (rawLeft === undefined) return -1;
    if (rawRight === undefined) return 1;
    const numLeft = Number(rawLeft);
    const numRight = Number(rawRight);
    if (Number.isFinite(numLeft) && Number.isFinite(numRight)) {
      if (numLeft !== numRight) return numLeft - numRight;
      continue;
    }
    const textCompare = rawLeft.localeCompare(rawRight);
    if (textCompare !== 0) return textCompare;
  }
  return 0;
}

export function compareVersions(a: string, b: string) {
  const left = parseVersion(a);
  const right = parseVersion(b);
  const length = Math.max(left.numbers.length, right.numbers.length);
  for (let index = 0; index < length; index += 1) {
    const numLeft = left.numbers[index] ?? 0;
    const numRight = right.numbers[index] ?? 0;
    if (numLeft !== numRight) return numLeft - numRight;
  }
  return comparePrerelease(left.prerelease, right.prerelease);
}

function classifyAsset(name: string): UpdateAsset["kind"] {
  if (/\.zip$/i.test(name)) return "zip";
  if (/\.tar\.gz$|\.tgz$/i.test(name)) return "tar";
  return "other";
}

function choosePreferredAsset(assets: UpdateAsset[]) {
  return assets.find((asset) => asset.kind === "zip")
    ?? assets.find((asset) => asset.kind === "tar")
    ?? assets[0]
    ?? null;
}

function formatRelease(release: GitHubRelease): UpdateInfo {
  const latestVersion = normalizeVersion(release.tag_name || release.name || "0.0.0");
  const currentVersion = normalizeVersion(__AISYNC_APP_VERSION__);
  const assets = (release.assets || [])
    .filter((asset): asset is Required<Pick<GitHubReleaseAsset, "name" | "browser_download_url">> & GitHubReleaseAsset =>
      Boolean(asset.name && asset.browser_download_url),
    )
    .map((asset) => ({
      name: asset.name,
      url: asset.browser_download_url,
      size: asset.size || 0,
      kind: classifyAsset(asset.name),
    }));
  return {
    currentVersion,
    latestVersion,
    hasUpdate: compareVersions(latestVersion, currentVersion) > 0,
    releaseName: release.name || release.tag_name || latestVersion,
    releaseUrl: release.html_url || RELEASES_URL,
    publishedAt: release.published_at || null,
    body: release.body || "",
    assets,
    preferredAsset: choosePreferredAsset(assets),
  };
}

export async function checkLatestRelease(): Promise<UpdateInfo> {
  const response = await fetch(RELEASE_API_URL, {
    headers: { Accept: "application/vnd.github+json" },
    cache: "no-store",
  });
  if (!response.ok) {
    throw new Error(`GitHub Releases 请求失败：${response.status}`);
  }
  return formatRelease(await response.json() as GitHubRelease);
}

export async function openExternalUrl(url: string): Promise<boolean> {
  if (!url) return false;
  if (typeof window !== "undefined") {
    const opened = window.open(url, "_blank", "noopener,noreferrer");
    return Boolean(opened);
  }
  return false;
}

export function formatAssetSize(size: number) {
  if (!Number.isFinite(size) || size <= 0) return "未知大小";
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}
