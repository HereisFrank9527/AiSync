const RELEASE_API_URL = "https://api.github.com/repos/HereisFrank9527/AiSync/releases/latest";
const RELEASES_URL = "https://github.com/HereisFrank9527/AiSync/releases/latest";

export interface UpdateAsset {
  name: string;
  url: string;
  size: number;
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

function normalizeVersion(value: string) {
  return value.trim().replace(/^v/i, "");
}

function compareVersions(a: string, b: string) {
  const left = normalizeVersion(a).split(/[.-]/);
  const right = normalizeVersion(b).split(/[.-]/);
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    const rawLeft = left[index] ?? "0";
    const rawRight = right[index] ?? "0";
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

function formatRelease(release: GitHubRelease): UpdateInfo {
  const latestVersion = normalizeVersion(release.tag_name || release.name || "0.0.0");
  const currentVersion = normalizeVersion(__AISYNC_APP_VERSION__);
  return {
    currentVersion,
    latestVersion,
    hasUpdate: compareVersions(latestVersion, currentVersion) > 0,
    releaseName: release.name || release.tag_name || latestVersion,
    releaseUrl: release.html_url || RELEASES_URL,
    publishedAt: release.published_at || null,
    body: release.body || "",
    assets: (release.assets || [])
      .filter((asset): asset is Required<Pick<GitHubReleaseAsset, "name" | "browser_download_url">> & GitHubReleaseAsset =>
        Boolean(asset.name && asset.browser_download_url),
      )
      .map((asset) => ({
        name: asset.name,
        url: asset.browser_download_url,
        size: asset.size || 0,
      })),
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
