import api from './client'

export interface TickerCandidate {
  ticker: string
  name: string
  exchange: string | null
  validated: boolean
}

export interface TickerLookupResponse {
  candidates: TickerCandidate[]
}

export const tickerApi = {
  lookup: async (companyName: string): Promise<TickerLookupResponse> => {
    const { data } = await api.post('/api/ticker/lookup', { company_name: companyName })
    return data
  },
}
