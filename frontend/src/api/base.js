const configuredBaseUrl = (
  import.meta.env
    ?.VITE_API_BASE_URL
  || ""
);


export const API_BASE_URL = (
  String(
    configuredBaseUrl,
  )
    .trim()
    .replace(
      /\/+$/,
      "",
    )
);


export const apiUrl = (
  path,
) => {
  const normalizedPath = (
    String(
      path,
    ).startsWith("/")
      ? String(path)
      : `/${path}`
  );

  return (
    `${API_BASE_URL}${normalizedPath}`
  );
};