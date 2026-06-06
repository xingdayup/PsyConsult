type PagesContext = {
  env: Record<string, string | undefined>
}

export async function onRequestGet({ env }: PagesContext) {
  return Response.json(
    {
      apiBaseUrl: env.VITE_API_BASE_URL || '',
      apiAuthToken: env.VITE_API_AUTH_TOKEN || '',
    },
    {
      headers: {
        'Cache-Control': 'no-store',
      },
    },
  )
}
